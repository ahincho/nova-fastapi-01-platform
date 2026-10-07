"""
El catálogo de la plataforma (ADR-031): el mismo código y el mismo mensaje en
todos los stacks de Nova.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from nova_fastapi.errors.failure import ApiFailureKind
from nova_fastapi.errors.ports import ErrorDescription, SanitizedError

INTERNAL_ERROR_CODE = "INTERNAL_SERVER_ERROR"
"""El código de un 5xx que la tabla no nombra."""

DEFAULT_ERROR_CODE = "REQUEST_ERROR"
"""El código de un 4xx que la tabla no nombra."""

VALIDATION_ERROR_CODE = "BAD_REQUEST"
"""
El código de un fallo de validación de la entrada. ADR-031 lo pide igual que
el de cualquier `INVALID_INPUT`, y así lo responden Spring Boot y Quarkus.
"""

# Los tres 5xx con nombre propio son los que le dicen al cliente si conviene
# reintentar -un 503 o un 504 sí, un 500 no- sin contarle la topología.
STATUS_ERROR_CODES: Mapping[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    406: "NOT_ACCEPTABLE",
    408: "REQUEST_TIMEOUT",
    409: "CONFLICT",
    410: "GONE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_ENTITY",
    429: "TOO_MANY_REQUESTS",
    500: INTERNAL_ERROR_CODE,
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}

DEFAULT_INTERNAL_ERROR_MESSAGE = "Error interno del servidor"
DEFAULT_REQUEST_ERROR_MESSAGE = "La solicitud no se pudo atender"

# Se indexan por status y no por código: un catálogo propio puede renombrar el
# código de un 404, y el mensaje sigue diciendo qué pasó.
STATUS_ERROR_MESSAGES: Mapping[int, str] = {
    400: "La solicitud no es válida",
    401: "Hace falta autenticarse",
    403: "No hay permiso para esta operación",
    404: "El recurso no existe",
    405: "El método no está permitido en este recurso",
    406: "No hay una representación en el formato pedido",
    408: "La solicitud tardó demasiado en llegar",
    409: "La operación choca con el estado actual del recurso",
    410: "El recurso ya no está disponible",
    415: "El tipo de contenido no está soportado",
    422: "La solicitud no se puede procesar",
    429: "Demasiadas solicitudes; conviene esperar antes de reintentar",
    500: DEFAULT_INTERNAL_ERROR_MESSAGE,
    502: "Una dependencia respondió con un error",
    503: "El servicio no está disponible en este momento",
    504: "Una dependencia no respondió a tiempo",
}


@dataclass(frozen=True)
class ErrorCodes:
    """
    Qué código lleva cada fallo que no trae uno propio. Un catálogo propio cambia
    solo lo que necesita: `ErrorCodes(by_status={409: "ALREADY_EXISTS"})` suma
    esa fila a las de Nova en vez de reemplazarlas.
    """

    validation: str = VALIDATION_ERROR_CODE
    by_status: Mapping[int, str] = field(default_factory=dict)
    request: str = DEFAULT_ERROR_CODE
    internal: str = INTERNAL_ERROR_CODE

    def code_for(self, status: int, kind: ApiFailureKind) -> str:
        if kind == "validation":
            return self.validation
        merged = {**STATUS_ERROR_CODES, **self.by_status}
        return merged.get(status, self.internal if status >= 500 else self.request)


def status_to_error_message(status: int) -> str:
    """El mensaje genérico de un status: el de todo 5xx, y el de un 4xx sin mensaje propio."""
    return STATUS_ERROR_MESSAGES.get(
        status,
        DEFAULT_INTERNAL_ERROR_MESSAGE if status >= 500 else DEFAULT_REQUEST_ERROR_MESSAGE,
    )


class NovaErrorCatalog:
    """
    El `ErrorCatalog` de Nova.

    En un 4xx, el código propio del error si lo trae y si no el del catálogo,
    con el mensaje propio si lo trae y si no el genérico de su status. En un
    5xx, siempre el código del catálogo y el mensaje genérico: el código propio,
    el mensaje y el proveedor cuentan qué falló por dentro, y eso va al log.

    `internal_error_message` reemplaza el mensaje de todo 5xx. Llega al cliente
    tal cual, así que nunca lleva la falla de fondo.
    """

    def __init__(
        self, codes: ErrorCodes | None = None, *, internal_error_message: str | None = None
    ) -> None:
        self.codes = codes or ErrorCodes()
        self.internal_error_message = internal_error_message

    def describe(self, error: SanitizedError, status: int) -> ErrorDescription:
        if status >= 500:
            return ErrorDescription(
                code=self.codes.code_for(status, "internal"),
                message=self.internal_error_message or status_to_error_message(status),
            )
        return ErrorDescription(
            code=error.code or self.codes.code_for(status, error.kind),
            message=error.message or status_to_error_message(status),
        )
