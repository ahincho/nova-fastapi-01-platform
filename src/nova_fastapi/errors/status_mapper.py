"""El `ErrorStatusMapper` de Nova: la tabla de ADR-031, fila por fila."""

from collections.abc import Mapping

from nova_fastapi.errors.layer import (
    ApplicationErrorType,
    DomainErrorType,
    ErrorType,
    InfrastructureErrorType,
    Layer,
    PlatformErrorType,
)
from nova_fastapi.errors.ports import ErrorClassification

# `domain` y `application` son 4xx porque son esperados; `infrastructure` y
# `platform` son 5xx porque son incidentes.
STATUS_BY_LAYER: Mapping[Layer, Mapping[ErrorType, int]] = {
    Layer.DOMAIN: {
        DomainErrorType.NOT_FOUND: 404,
        DomainErrorType.CONFLICT: 409,
        DomainErrorType.RULE_VIOLATION: 422,
    },
    Layer.APPLICATION: {
        ApplicationErrorType.INVALID_INPUT: 400,
        ApplicationErrorType.CONFLICT: 409,
        ApplicationErrorType.UNPROCESSABLE: 422,
        ApplicationErrorType.UNAUTHENTICATED: 401,
        ApplicationErrorType.FORBIDDEN: 403,
        ApplicationErrorType.RATE_LIMITED: 429,
    },
    Layer.INFRASTRUCTURE: {
        InfrastructureErrorType.UNAVAILABLE: 503,
        InfrastructureErrorType.TIMEOUT: 504,
        InfrastructureErrorType.BAD_GATEWAY: 502,
    },
    Layer.PLATFORM: {
        PlatformErrorType.INTERNAL: 500,
    },
}


class NovaErrorStatusMapper:
    """
    La tabla de ADR-031. Para cambiar una sola fila, un mapper propio consulta
    la suya y cae a este para el resto.
    """

    def status_of(self, error: ErrorClassification) -> int:
        # Un tipo fuera de la tabla solo puede venir de código sin tipos. Sale
        # como 500 porque es un defecto, y un 500 es lo único que no promete nada.
        return STATUS_BY_LAYER.get(error.layer, {}).get(error.type, 500)
