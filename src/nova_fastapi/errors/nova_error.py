"""
Los errores de Nova (ADR-031): una clase por capa, con una fábrica por tipo.

No importan ningún framework web, y ése es el punto: el mismo caso de uso corre
detrás de HTTP o de un consumidor de cola, y quien lanza no sabe de status. El
HTTP lo decide la plataforma con `ErrorStatusMapper`.
"""

import math
from dataclasses import dataclass
from typing import Any

from nova_fastapi.errors.layer import (
    ApplicationErrorType,
    DomainErrorType,
    ErrorType,
    InfrastructureErrorType,
    Layer,
    PlatformErrorType,
)
from nova_fastapi.observability.context import current_request_id


@dataclass(frozen=True)
class FieldError:
    """
    Un campo de la entrada que no pasó, en un `INVALID_INPUT`.

    `field` lleva la ruta con puntos si está anidado (`address.zip_code`), y es
    una cadena vacía para una restricción del objeto entero. `code` es opcional:
    sin él, la entrada lleva el código del error, que con el catálogo de Nova es
    `VALIDATION_ERROR` o `BAD_REQUEST`.
    """

    field: str
    message: str
    code: str | None = None


def _normalize_retry_after(seconds: float | None) -> int | None:
    """
    `Retry-After` va en segundos enteros, así que se redondea hacia arriba:
    esperar de menos es lo que vuelve a chocar. Un valor negativo o que no es un
    número finito se descarta en vez de lanzar: lanzar aquí reemplazaría el
    error que se estaba construyendo por uno que nadie pensó responder.
    """
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return math.ceil(seconds)


class NovaError(Exception):
    """
    La base de los errores de Nova. No se lanza directamente: se lanza una de
    las cuatro clases de capa con su fábrica, como `DomainError.not_found(...)`.

    `trace_id` se toma del contexto de la petición al construir el error, y no
    al responder: para entonces el contexto se puede haber perdido. Fuera de una
    petición queda en None; nunca se inventa.

    `upstream` y `cause` van al log y nunca al cliente.
    """

    def __init__(
        self,
        *,
        layer: Layer,
        type: ErrorType,
        message: str,
        code: str | None = None,
        field_errors: tuple[FieldError, ...] | list[FieldError] = (),
        retry_after: float | None = None,
        upstream: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.layer = layer
        self.type = type
        self.message = message
        self.code = code
        self.field_errors = tuple(field_errors)
        self.retry_after = _normalize_retry_after(retry_after)
        self.upstream = upstream
        self.trace_id = current_request_id()
        if cause is not None:
            self.__cause__ = cause

    @property
    def cause(self) -> BaseException | None:
        return self.__cause__

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.type.value}, {self.message!r})"


class DomainError(NovaError):
    """
    Un error de negocio: esperado, se registra en `warn` y sin stack.

        raise DomainError.not_found("Pedido no encontrado", code="ORDER_NOT_FOUND")
    """

    def __init__(
        self,
        type: DomainErrorType,
        message: str,
        *,
        code: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(layer=Layer.DOMAIN, type=type, message=message, code=code, cause=cause)

    @classmethod
    def not_found(cls, message: str, **options: Any) -> "DomainError":
        """404: el recurso de negocio no existe."""
        return cls(DomainErrorType.NOT_FOUND, message, **options)

    @classmethod
    def conflict(cls, message: str, **options: Any) -> "DomainError":
        """409: el estado del recurso no admite la operación."""
        return cls(DomainErrorType.CONFLICT, message, **options)

    @classmethod
    def rule_violation(cls, message: str, **options: Any) -> "DomainError":
        """422: una regla de negocio dijo que no."""
        return cls(DomainErrorType.RULE_VIOLATION, message, **options)


class ApplicationError(NovaError):
    """
    Un error de la operación que se pidió: la entrada, la identidad o un límite.
    Esperado, se registra en `warn` y sin stack.

        raise ApplicationError.invalid_input(
            "La inscripción no es válida",
            [FieldError("period_id", "Debe ser un entero")],
        )
    """

    def __init__(
        self,
        type: ApplicationErrorType,
        message: str,
        *,
        code: str | None = None,
        field_errors: tuple[FieldError, ...] | list[FieldError] = (),
        retry_after: float | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            layer=Layer.APPLICATION,
            type=type,
            message=message,
            code=code,
            field_errors=field_errors,
            retry_after=retry_after,
            cause=cause,
        )

    @classmethod
    def invalid_input(
        cls,
        message: str,
        field_errors: tuple[FieldError, ...] | list[FieldError] = (),
        **options: Any,
    ) -> "ApplicationError":
        """400: la entrada no es válida. Cada campo viaja como su propia entrada del sobre."""
        return cls(
            ApplicationErrorType.INVALID_INPUT, message, field_errors=field_errors, **options
        )

    @classmethod
    def conflict(cls, message: str, **options: Any) -> "ApplicationError":
        """409: choca con otra operación en curso. Con `retry_after`, cuándo reintentar."""
        return cls(ApplicationErrorType.CONFLICT, message, **options)

    @classmethod
    def unprocessable(cls, message: str, **options: Any) -> "ApplicationError":
        """422: la entrada es válida pero no se puede procesar."""
        return cls(ApplicationErrorType.UNPROCESSABLE, message, **options)

    @classmethod
    def unauthenticated(cls, message: str, **options: Any) -> "ApplicationError":
        """401: falta la identidad o no es válida."""
        return cls(ApplicationErrorType.UNAUTHENTICATED, message, **options)

    @classmethod
    def forbidden(cls, message: str, **options: Any) -> "ApplicationError":
        """403: la identidad no tiene permiso."""
        return cls(ApplicationErrorType.FORBIDDEN, message, **options)

    @classmethod
    def rate_limited(cls, message: str, **options: Any) -> "ApplicationError":
        """429: se superó un límite. Con `retry_after`, cuándo se libera."""
        return cls(ApplicationErrorType.RATE_LIMITED, message, **options)


# Solo para el log, por eso en inglés, como el resto de los mensajes que
# escribe la plataforma en los otros stacks.
_INFRASTRUCTURE_LOG_MESSAGES = {
    InfrastructureErrorType.UNAVAILABLE: "is unavailable",
    InfrastructureErrorType.TIMEOUT: "did not respond in time",
    InfrastructureErrorType.BAD_GATEWAY: "answered with an invalid response",
}


class InfrastructureError(NovaError):
    """
    Una dependencia falló: no está, no contestó a tiempo o contestó algo
    inválido. Es un incidente: se registra en `error`, con la causa completa.

    El nombre del proveedor va solo al log, en el campo `upstream`. El cuerpo
    lleva el código genérico del status, que alcanza para saber si conviene
    reintentar sin conocer la topología.

        raise InfrastructureError.timeout("gemini", cause=e)
    """

    def __init__(
        self,
        type: InfrastructureErrorType,
        upstream: str | None,
        *,
        message: str | None = None,
        code: str | None = None,
        retry_after: float | None = None,
        cause: BaseException | None = None,
    ) -> None:
        subject = "An upstream" if upstream is None else f"Upstream {upstream}"
        super().__init__(
            layer=Layer.INFRASTRUCTURE,
            type=type,
            message=message or f"{subject} {_INFRASTRUCTURE_LOG_MESSAGES[type]}",
            code=code,
            retry_after=retry_after,
            upstream=upstream,
            cause=cause,
        )

    @classmethod
    def unavailable(cls, upstream: str, **options: Any) -> "InfrastructureError":
        """503: la dependencia no está disponible. Con `retry_after`, cuándo reintentar."""
        return cls(InfrastructureErrorType.UNAVAILABLE, upstream, **options)

    @classmethod
    def timeout(cls, upstream: str, **options: Any) -> "InfrastructureError":
        """504: la dependencia no respondió a tiempo."""
        return cls(InfrastructureErrorType.TIMEOUT, upstream, **options)

    @classmethod
    def bad_gateway(cls, upstream: str, **options: Any) -> "InfrastructureError":
        """502: la dependencia respondió algo inválido."""
        return cls(InfrastructureErrorType.BAD_GATEWAY, upstream, **options)


class PlatformError(NovaError):
    """
    Un defecto o una falla del propio servicio durante una petición. Es un
    incidente, y el cliente recibe solo el mensaje genérico.

    Cualquier excepción que no sea de Nova ni del framework llega al cliente
    como uno de estos, así que lanzarlo a mano solo hace falta para ponerle un
    mensaje de log o un código propio. Un error de configuración al arrancar no
    se responde: la aplicación no arranca.
    """

    def __init__(
        self,
        type: PlatformErrorType,
        message: str,
        *,
        code: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(layer=Layer.PLATFORM, type=type, message=message, code=code, cause=cause)

    @classmethod
    def internal(cls, message: str, **options: Any) -> "PlatformError":
        """500: un defecto o una falla del propio servicio."""
        return cls(PlatformErrorType.INTERNAL, message, **options)
