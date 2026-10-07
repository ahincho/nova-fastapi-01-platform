"""Las capas y sus tipos (ADR-031)."""

from enum import StrEnum


class Layer(StrEnum):
    """
    La capa donde nació un error.

    Es la regla que ordena el módulo: `domain` y `application` son esperados, e
    `infrastructure` y `platform` son incidentes. Un 404 de negocio no tiene que
    despertar a nadie, y un proveedor que dejó de contestar sí; clasificar por
    capa es lo que permite alertar sobre lo segundo sin que lo primero ensucie
    la señal.

    El valor es el que se escribe en el campo `layer` del log.
    """

    DOMAIN = "domain"
    APPLICATION = "application"
    INFRASTRUCTURE = "infrastructure"
    PLATFORM = "platform"


# Un tipo enumerado por capa, y no un texto libre: sin tipos, cada servicio
# inventa su nombre y el tablero vuelve a agrupar por cadenas que no coinciden.
# Cada valor es una fila de la tabla de ADR-031; el status HTTP que le toca lo
# decide `ErrorStatusMapper`, no quien lanza.


class DomainErrorType(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    """404: el recurso de negocio no existe."""
    CONFLICT = "CONFLICT"
    """409: el estado del recurso no admite la operación."""
    RULE_VIOLATION = "RULE_VIOLATION"
    """422: una regla de negocio dijo que no."""


class ApplicationErrorType(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    """400: la entrada no es válida; lleva los errores por campo."""
    CONFLICT = "CONFLICT"
    """409: la operación choca con otra en curso."""
    UNPROCESSABLE = "UNPROCESSABLE"
    """422: la entrada es válida pero no se puede procesar."""
    UNAUTHENTICATED = "UNAUTHENTICATED"
    """401: falta la identidad o no es válida."""
    FORBIDDEN = "FORBIDDEN"
    """403: la identidad no tiene permiso."""
    RATE_LIMITED = "RATE_LIMITED"
    """429: se superó un límite."""


class InfrastructureErrorType(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    """503: una dependencia no está disponible."""
    TIMEOUT = "TIMEOUT"
    """504: una dependencia no respondió a tiempo."""
    BAD_GATEWAY = "BAD_GATEWAY"
    """502: una dependencia respondió algo inválido."""


class PlatformErrorType(StrEnum):
    INTERNAL = "INTERNAL"
    """500: un defecto o una falla del propio servicio."""


type ErrorType = (
    DomainErrorType | ApplicationErrorType | InfrastructureErrorType | PlatformErrorType
)
