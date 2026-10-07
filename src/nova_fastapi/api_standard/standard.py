"""
El puerto del estándar de API y el de Nova.

El estándar decide la forma de todo lo que un servicio contesta, lo que devuelve
y lo que rechaza. Lo que no está aquí es deliberado: qué respuestas pasan por el
estándar, qué status corresponde a cada excepción y qué se le puede decir al
cliente en un 5xx son reglas del núcleo, y ningún estándar las cambia. El
estándar decide la forma; el núcleo decide qué se puede decir (ADR-034).
"""

from typing import Any, Protocol

from nova_fastapi.api_standard.envelope import ApiErrorItem, ApiMetadata, ApiResponse, ok
from nova_fastapi.api_standard.serializer import NovaErrorSerializer
from nova_fastapi.errors.catalog import ErrorCodes, NovaErrorCatalog
from nova_fastapi.errors.failure import ApiFailure, ApiWire
from nova_fastapi.errors.ports import ErrorCatalog

type OpenApiSchema = dict[str, Any]


class ApiStandard(Protocol):
    """
    La forma de las respuestas. Nova registra `NovaEnvelopeStandard` cuando nadie
    declara otro, y un servicio o un perfil lo reemplaza entero.
    """

    error_catalog: ErrorCatalog | None
    """El catálogo con que nombra los fallos. None deja el de Nova."""

    def success(self, payload: Any, status: int) -> Any:
        """El cuerpo de un éxito, como lo serializa FastAPI con `success_model`."""
        ...

    def success_model(self, payload_type: Any) -> Any:
        """El tipo con que se documenta y se valida un éxito cuyo resultado es `payload_type`."""
        ...

    def failure(self, failure: ApiFailure) -> ApiWire:
        """El cuerpo y las cabeceras de un fallo."""
        ...

    def owns(self, payload: Any) -> bool:
        """Si `payload` ya es un cuerpo de este estándar, para no envolverlo dos veces."""
        ...

    def openapi_components(self) -> dict[str, OpenApiSchema]:
        """Los esquemas que el estándar agrega a `components.schemas`."""
        ...

    def openapi_failure(self, status: int) -> tuple[str, OpenApiSchema]:
        """El tipo de contenido y el esquema de un fallo con este status."""
        ...


ENVELOPE_SCHEMA = "ApiEnvelope"
ERROR_ITEM_SCHEMA = "ApiErrorItem"
METADATA_SCHEMA = "ApiMetadata"


def _ref(name: str) -> OpenApiSchema:
    return {"$ref": f"#/components/schemas/{name}"}


class NovaEnvelopeStandard:
    """
    El estándar de Nova: el sobre `{ success, status, data, errors }`.

    Un error suma `metadata.traceId` y, si dice cuánto esperar, la cabecera
    `Retry-After` (ADR-031); un éxito no cambia. `codes` cambia solo los códigos
    que se nombran y deja los demás de Nova:

        NovaEnvelopeStandard(codes=ErrorCodes(by_status={409: "ALREADY_EXISTS"}))
    """

    def __init__(self, codes: ErrorCodes | None = None) -> None:
        self.codes = codes or ErrorCodes()
        self.error_catalog: ErrorCatalog | None = NovaErrorCatalog(self.codes)
        self._serializer = NovaErrorSerializer(self.codes)

    def success(self, payload: Any, status: int) -> ApiResponse[Any]:
        return ok(payload, status)

    def success_model(self, payload_type: Any) -> Any:
        return ApiResponse[payload_type]

    def failure(self, failure: ApiFailure) -> ApiWire:
        return self._serializer.serialize(failure)

    def owns(self, payload: Any) -> bool:
        return isinstance(payload, ApiResponse)

    def openapi_components(self) -> dict[str, OpenApiSchema]:
        ref_template = "#/components/schemas/{model}"
        return {
            ERROR_ITEM_SCHEMA: ApiErrorItem.model_json_schema(ref_template=ref_template),
            METADATA_SCHEMA: ApiMetadata.model_json_schema(
                ref_template=ref_template, by_alias=True
            ),
            ENVELOPE_SCHEMA: {
                "type": "object",
                "title": ENVELOPE_SCHEMA,
                "properties": {
                    "success": {"type": "boolean"},
                    "status": {"type": "integer"},
                    "data": {},
                    "errors": {"type": "array", "items": _ref(ERROR_ITEM_SCHEMA)},
                    "metadata": {
                        "description": "Presente en las respuestas de error.",
                        "allOf": [_ref(METADATA_SCHEMA)],
                    },
                },
                "required": ["success", "status", "data", "errors"],
            },
        }

    def openapi_failure(self, status: int) -> tuple[str, OpenApiSchema]:
        return "application/json", {
            "allOf": [
                _ref(ENVELOPE_SCHEMA),
                {
                    # Un error siempre trae `metadata`, con el `traceId` que se
                    # cita al reportarlo; el sobre base la declara opcional.
                    "required": ["metadata"],
                    "properties": {
                        "success": {"type": "boolean", "examples": [False]},
                        "status": {"type": "integer", "examples": [status]},
                        "data": {"type": "null"},
                    },
                },
            ]
        }
