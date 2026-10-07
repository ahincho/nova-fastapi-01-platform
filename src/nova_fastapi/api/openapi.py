"""
La documentación de los errores en `/docs`, con el estándar activo.

FastAPI documenta por su cuenta un 422 con un cuerpo que la API ya no responde:
un fallo de validación sale como 400 con el sobre. Aquí se corrige eso sobre el
esquema ya armado, y se agregan los esquemas del estándar.
"""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from nova_fastapi.api_standard.standard import ApiStandard
from nova_fastapi.errors.catalog import status_to_error_message

VALIDATION_DESCRIPTION = "La entrada no es válida: `errors` lleva una entrada por cada campo."

# Los esquemas con que FastAPI documenta su 422, que ya no describen nada.
_FASTAPI_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")


def _is_fastapi_validation(response: dict[str, Any]) -> bool:
    schema = response.get("content", {}).get("application/json", {}).get("schema", {})
    return str(schema.get("$ref", "")).endswith("/HTTPValidationError")


def failure_response(standard: ApiStandard, status: int, description: str | None = None) -> dict:
    """La respuesta documentada de un fallo con este status."""
    content_type, schema = standard.openapi_failure(status)
    return {
        "description": description or status_to_error_message(status),
        "content": {content_type: {"schema": schema}},
    }


def document(schema: dict[str, Any], standard: ApiStandard) -> dict[str, Any]:
    """
    Ajusta el esquema: el 422 de FastAPI pasa a ser el 400 con el sobre, y se
    agregan los esquemas del estándar. Aplicarlo otra vez no cambia nada.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            validation = responses.get("422")
            if validation is not None and _is_fastapi_validation(validation):
                del responses["422"]
                responses.setdefault("400", failure_response(standard, 400, VALIDATION_DESCRIPTION))

    definitions = schema.setdefault("components", {}).setdefault("schemas", {})
    for name in _FASTAPI_VALIDATION_SCHEMAS:
        definitions.pop(name, None)
    definitions.update(standard.openapi_components())
    return schema


def patch_openapi(app: FastAPI, standard: ApiStandard) -> None:
    """
    Hace que `app.openapi()` entregue el esquema ajustado.

    Se ajusta en cada llamada y no una sola vez: FastAPI guarda el esquema y lo
    vuelve a armar si cambian las rutas, y el nuevo llega sin ajustar.
    """
    original: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        return document(original(), standard)

    app.openapi = openapi  # type: ignore[method-assign]


def error_responses(
    *statuses: int, standard: ApiStandard | None = None
) -> dict[int | str, dict[str, Any]]:
    """
    Los fallos que un endpoint documenta, para su parámetro `responses`:

        @router.get("/orders/{id}", responses=error_responses(404, 409))
    """
    from nova_fastapi.api.route import NovaRoute

    active = standard or NovaRoute.standard
    return {status: failure_response(active, status) for status in statuses}
