"""
Toda excepción de una petición, respondida con el estándar activo.

El reparto es la razón de ser de este archivo. Aquí se decide qué se puede
decir: el status de cada excepción, que un 5xx no lleve ni su mensaje ni su
código ni su proveedor, qué campos fallaron en una validación. Los puertos
-el status, el catálogo, el serializador y el estándar- reciben eso ya decidido
y solo le dan forma, así que uno mal escrito no tiene de dónde filtrar lo que
este archivo le quitó (ADR-034).

El orden es el que lo hace verdad: primero se lee la excepción entera, después
se escribe una sola línea de log con todo lo que trae -el proveedor, la causa,
el mensaje real-, y solo entonces se llama a los puertos con el fallo saneado
(ADR-035).
"""

import logging
import uuid
from dataclasses import dataclass
from http import HTTPStatus

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from nova_fastapi.api.profile import NovaConfig
from nova_fastapi.api.validation import field_errors
from nova_fastapi.errors.catalog import NovaErrorCatalog
from nova_fastapi.errors.failure import ApiFailure, ApiFailureItem, ApiFailureKind, ApiWire
from nova_fastapi.errors.layer import (
    ApplicationErrorType,
    ErrorType,
    InfrastructureErrorType,
    Layer,
    PlatformErrorType,
)
from nova_fastapi.errors.nova_error import FieldError, NovaError, PlatformError
from nova_fastapi.errors.ports import ErrorClassification, ErrorDescription, SanitizedError
from nova_fastapi.observability.context import current_request_id

logger = logging.getLogger("nova_fastapi.errors")

# Cómo se lee una excepción del framework (ADR-031): por su status. Un 4xx es
# de `application`, con el tipo de la fila que tiene ese status; un 404 o un 405
# no tienen fila y quedan sin tipo. Los 502, 503 y 504 son fallas de una
# dependencia, y cualquier otro 5xx es del propio servicio.
_APPLICATION_TYPES: dict[int, ApplicationErrorType] = {
    400: ApplicationErrorType.INVALID_INPUT,
    401: ApplicationErrorType.UNAUTHENTICATED,
    403: ApplicationErrorType.FORBIDDEN,
    409: ApplicationErrorType.CONFLICT,
    422: ApplicationErrorType.UNPROCESSABLE,
    429: ApplicationErrorType.RATE_LIMITED,
}
_INFRASTRUCTURE_TYPES: dict[int, InfrastructureErrorType] = {
    502: InfrastructureErrorType.BAD_GATEWAY,
    503: InfrastructureErrorType.UNAVAILABLE,
    504: InfrastructureErrorType.TIMEOUT,
}

_NOVA_CATALOG = NovaErrorCatalog()


@dataclass(frozen=True)
class _Classified:
    """
    Lo que se sabe de una excepción una vez leída. Tiene el proveedor y la causa:
    solo el log la ve entera.
    """

    layer: Layer
    type: ErrorType | None
    status: int
    kind: ApiFailureKind
    code: str | None
    own_message: str | None
    log_message: str
    field_errors: tuple[FieldError, ...] = ()
    retry_after: int | None = None
    upstream: str | None = None
    trace_id: str | None = None
    headers: dict[str, str] | None = None


def _classify_status(status: int) -> tuple[Layer, ErrorType | None]:
    if status < 500:
        return Layer.APPLICATION, _APPLICATION_TYPES.get(status)
    infrastructure = _INFRASTRUCTURE_TYPES.get(status)
    if infrastructure is None:
        return Layer.PLATFORM, PlatformErrorType.INTERNAL
    return Layer.INFRASTRUCTURE, infrastructure


def _is_incident(layer: Layer) -> bool:
    return layer in (Layer.INFRASTRUCTURE, Layer.PLATFORM)


def _own_message(detail: object, status: int) -> str | None:
    """
    El mensaje que escribió quien lanzó la excepción del framework. None cuando
    no escribió ninguno, que es cuando el texto es el que pone Starlette solo:
    ahí el catálogo pone el de su status.
    """
    if not isinstance(detail, str) or not detail.strip():
        return None
    try:
        default = HTTPStatus(status).phrase
    except ValueError:
        default = None
    return None if detail == default else detail


class ErrorResponder:
    """Convierte una excepción en la respuesta del estándar activo, y la registra."""

    def __init__(self, config: NovaConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Clasificar
    # ------------------------------------------------------------------
    def classify(self, exception: BaseException) -> _Classified:
        if isinstance(exception, RequestValidationError):
            return _Classified(
                layer=Layer.APPLICATION,
                type=ApplicationErrorType.INVALID_INPUT,
                status=400,
                kind="validation",
                code=None,
                own_message=None,
                log_message="Request validation failed",
                field_errors=field_errors(exception.errors()),
                trace_id=current_request_id(),
            )
        if isinstance(exception, StarletteHTTPException):
            status = exception.status_code
            layer, type_ = _classify_status(status)
            return _Classified(
                layer=layer,
                type=type_,
                status=status,
                kind="internal" if status >= 500 else "request",
                # Un código propio, si quien la lanzó le puso uno.
                code=getattr(exception, "error_code", None),
                own_message=_own_message(exception.detail, status),
                log_message=str(exception.detail),
                trace_id=current_request_id(),
                headers=dict(exception.headers or {}),
            )
        error = exception if isinstance(exception, NovaError) else self._platform_error(exception)
        # Al puerto de status le llega cómo está clasificado el error, y no el
        # error: devuelve un número y no necesita el proveedor ni la causa.
        status = self.config.status_mapper.status_of(
            ErrorClassification(layer=error.layer, type=error.type, code=error.code)
        )
        return _Classified(
            layer=error.layer,
            type=error.type,
            status=status,
            kind="internal" if status >= 500 else "request",
            code=error.code,
            own_message=error.message.strip() or None,
            log_message=error.message,
            field_errors=error.field_errors,
            retry_after=error.retry_after,
            upstream=error.upstream,
            trace_id=error.trace_id,
        )

    @staticmethod
    def _platform_error(exception: BaseException) -> PlatformError:
        return PlatformError.internal(str(exception) or "Unhandled exception", cause=exception)

    # ------------------------------------------------------------------
    # Sanear y describir
    # ------------------------------------------------------------------
    def failure_of(
        self, classified: _Classified, request: Request
    ) -> tuple[ApiFailure, ErrorDescription]:
        """
        El fallo saneado que reciben los puertos. La regla que ningún puerto puede
        tocar: por encima de 500 el error no trae ni su código, ni su mensaje, ni
        sus campos, ni el proveedor, ni la causa.
        """
        expected = classified.status < 500
        sanitized = SanitizedError(
            kind=classified.kind,
            layer=classified.layer,
            type=classified.type,
            code=classified.code if expected else None,
            message=classified.own_message if expected else None,
            field_errors=classified.field_errors if expected else (),
        )
        description = self._describe(sanitized, classified.status)
        # El que el error tomó al nacer; si nació fuera de una petición, el de la
        # que se está contestando; si ni ese existe, uno nuevo: sin él el cliente
        # no tiene nada que citar, y el log lleva el mismo valor que el cuerpo.
        trace_id = (
            classified.trace_id
            or current_request_id()
            or getattr(request.state, "request_id", None)
            or str(uuid.uuid4())
        )
        # Una entrada por campo, para que el formulario sepa qué marcar. Sin
        # campos, una sola con lo que decidió el catálogo.
        if sanitized.field_errors:
            errors = tuple(
                ApiFailureItem(
                    code=field.code or description.code, message=field.message, field=field.field
                )
                for field in sanitized.field_errors
            )
        else:
            errors = (ApiFailureItem(code=description.code, message=description.message),)
        failure = ApiFailure(
            status=classified.status,
            kind=classified.kind,
            layer=classified.layer,
            trace_id=trace_id,
            retry_after=classified.retry_after,
            errors=errors,
        )
        return failure, description

    def _describe(self, sanitized: SanitizedError, status: int) -> ErrorDescription:
        """
        Manda, en este orden, el catálogo que declaró el servicio o su perfil, el
        del estándar activo y el de Nova. `internal_error_message` cambia el
        mensaje de todo 5xx de quien no declaró un catálogo propio.
        """
        declared = self.config.catalog
        catalog = declared or self.config.standard.error_catalog or _NOVA_CATALOG
        description = catalog.describe(sanitized, status)
        if declared is None and status >= 500 and self.config.internal_error_message:
            return ErrorDescription(description.code, self.config.internal_error_message)
        return description

    # ------------------------------------------------------------------
    # Escribir
    # ------------------------------------------------------------------
    def wire_of(self, failure: ApiFailure) -> ApiWire:
        """El cuerpo y las cabeceras: el serializador declarado, o el estándar activo."""
        if self.config.serializer is not None:
            return self.config.serializer.serialize(failure)
        return self.config.standard.failure(failure)

    def respond(self, request: Request, exception: BaseException) -> Response:
        classified = self.classify(exception)
        failure, description = self.failure_of(classified, request)
        self._log(exception, classified, failure, description, request)
        wire = self.wire_of(failure)
        headers = {**(classified.headers or {}), **dict(wire.headers)}
        return JSONResponse(
            wire.body,
            status_code=failure.status,
            headers=headers,
            media_type=wire.content_type or "application/json",
        )

    def _log(
        self,
        exception: BaseException,
        classified: _Classified,
        failure: ApiFailure,
        description: ErrorDescription,
        request: Request,
    ) -> None:
        # Los nombres de estos campos son el contrato con el índice de logs de
        # Nova, el mismo en todos los stacks: `traceId` y `statusCode` son por los
        # que están escritas las consultas y los tableros.
        detail: dict[str, object] = {
            "statusCode": failure.status,
            "traceId": failure.trace_id,
            "layer": classified.layer.value,
            "type": classified.type.value if classified.type else None,
            "code": description.code,
            "method": request.method,
            "path": request.url.path,
            "errors": [
                {"code": item.code, "message": item.message, "field": item.field}
                for item in failure.errors
            ],
        }
        if classified.upstream is not None:
            detail["upstream"] = {"upstream": classified.upstream}
        # El nivel lo decide la capa y no el status (ADR-031): lo esperado va en
        # `warning` sin el stack, que apunta al código que rechazó bien la
        # petición; un incidente va en `error`, con la causa completa.
        if _is_incident(classified.layer):
            logger.error(classified.log_message, extra={"nova": detail}, exc_info=exception)
        else:
            logger.warning(classified.log_message, extra={"nova": detail})


class ErrorMiddleware:
    """
    Responde con el estándar lo que ningún manejador de FastAPI atrapó.

    Va por dentro de los middlewares que el servicio agrega después de instalar
    Nova, como CORS: así un 500 sale con las mismas cabeceras que cualquier otra
    respuesta. El manejador de errores no previstos de Starlette corre afuera de
    todos y respondería sin ellas.
    """

    def __init__(self, app: ASGIApp, *, responder: ErrorResponder) -> None:
        self.app = app
        self.responder = responder

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: dict) -> None:  # type: ignore[type-arg]
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exception:
            # Con la respuesta ya empezada no hay cómo cambiarla: queda para el
            # servidor, que corta la conexión y registra el error.
            if started:
                raise
            response = self.responder.respond(Request(scope, receive), exception)
            await response(scope, receive, send)
