"""
`install_nova`: Nova en una aplicación de FastAPI, con una línea.

Es el equivalente de `NovaModule.forRoot(...)` en NestJS y del starter en Spring
Boot.
"""

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

from nova_fastapi.api.errors import ErrorMiddleware, ErrorResponder
from nova_fastapi.api.openapi import patch_openapi
from nova_fastapi.api.profile import NovaConfig, Profile
from nova_fastapi.api.route import NovaRoute
from nova_fastapi.api_standard.standard import ApiStandard
from nova_fastapi.errors.nova_error import NovaError
from nova_fastapi.errors.ports import ErrorCatalog, ErrorSerializer, ErrorStatusMapper
from nova_fastapi.observability.request_context import RequestContextMiddleware


def install_nova(
    app: FastAPI,
    *,
    profile: Profile | None = None,
    request_id_accept: Sequence[str] | None = None,
    request_id_echo: str | None = None,
    standard: ApiStandard | None = None,
    status_mapper: ErrorStatusMapper | None = None,
    catalog: ErrorCatalog | None = None,
    serializer: ErrorSerializer | None = None,
    internal_error_message: str | None = None,
) -> NovaConfig:
    """
    Instala Nova en `app` y devuelve la configuración resuelta.

    - Toda excepción sale con el estándar: las de Nova, las de FastAPI y
      Starlette, la validación (400, con un error por campo) y lo no previsto
      (500, sin nada interno). Cada una deja una línea de log con su capa.
    - Cada petición tiene su id: el que trae en una cabecera aceptada o uno
      nuevo, devuelto en la cabecera de eco y citado en cada error.
    - Las rutas que se declaren en `app` envuelven su éxito en el sobre. Las de
      un `APIRouter` lo hacen con `route_class=NovaRoute`.
    - `/docs` documenta los errores con el sobre.

    Lo que no se pasa sale del perfil y, si el perfil no lo trae, de Nova.

    Conviene llamarla antes de agregar otros middlewares, como CORS: los que se
    agregan después quedan por fuera, así que también un error no previsto sale
    con sus cabeceras.
    """
    config = NovaConfig().merged(
        profile,
        request_id_accept=request_id_accept,
        request_id_echo=request_id_echo,
        standard=standard,
        status_mapper=status_mapper,
        catalog=catalog,
        serializer=serializer,
        internal_error_message=internal_error_message,
    )
    responder = ErrorResponder(config)

    async def handle(request: Request, exception: Exception) -> Response:
        return responder.respond(request, exception)

    # Los que FastAPI ya maneja se reemplazan; los de Nova se manejan aquí para
    # no depender del orden de los middlewares.
    for exception_type in (StarletteHTTPException, RequestValidationError, NovaError):
        app.add_exception_handler(exception_type, handle)

    # Lo último que se agrega queda por fuera: el contexto envuelve al manejo de
    # errores, así un error no previsto ya tiene su id.
    app.add_middleware(ErrorMiddleware, responder=responder)
    app.add_middleware(
        RequestContextMiddleware,
        accept=config.request_id_accept,
        echo=config.request_id_echo,
    )

    app.router.route_class = NovaRoute
    patch_openapi(app, config.standard)
    app.state.nova = config
    return config
