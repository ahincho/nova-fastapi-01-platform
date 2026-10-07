"""
El sobre de Nova: `{ success, status, data, errors }`, el mismo para un éxito y
para un error (ADR-031).

`data` y `errors` se excluyen entre sí por construcción: un éxito lleva
`errors` vacío y un error lleva `data: null`. Nada lo impone en el tipo, por eso
nadie arma el sobre a mano: lo arman `ok` y `failed`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorItem(BaseModel):
    """
    Una entrada de error. `field` nombra la entrada que falló, y es None en todo
    lo que no es un error de validación: nunca falta, así que quien lo lee no
    tiene que preguntar si existe.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        description="Estable, para decidir en el código del cliente", examples=["NOT_FOUND"]
    )
    message: str = Field(
        description="Para la persona, en español", examples=["El recurso no existe"]
    )
    field: str | None = Field(default=None, description="El campo, con puntos si está anidado")


class ApiMetadata(BaseModel):
    """
    Lo que acompaña a una respuesta sin ser su resultado ni uno de sus errores.

    Hoy lleva solo el `traceId`, y solo en los errores: es lo que alguien puede
    citar al reportar una falla, porque es el mismo valor de la línea de log. Un
    éxito no lo trae en el cuerpo: ya viaja en la cabecera de correlación.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    trace_id: str | None = Field(
        alias="traceId",
        description="El id de la petición, el mismo del log y de la cabecera de correlación",
    )


class ApiResponse[T](BaseModel):
    """La respuesta de todo endpoint de Nova, exitosa o fallida."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    success: bool
    status: int
    data: T | None = None
    errors: list[ApiErrorItem] = Field(default_factory=list)
    metadata: ApiMetadata | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Presente en las respuestas de error",
    )


def ok(payload: Any, status: int = 200) -> ApiResponse[Any]:
    """Un éxito con su resultado."""
    return ApiResponse[Any](success=True, status=status, data=payload, errors=[])


def failed(status: int, errors: list[ApiErrorItem], *, trace_id: str | None) -> ApiResponse[Any]:
    """Un error, con sus entradas y el `traceId` que se cita al reportarlo."""
    return ApiResponse[Any](
        success=False,
        status=status,
        data=None,
        errors=errors,
        metadata=ApiMetadata(trace_id=trace_id),
    )


def is_api_response(payload: Any) -> bool:
    """Si `payload` ya es un sobre de Nova, para no envolverlo dos veces."""
    return isinstance(payload, ApiResponse)
