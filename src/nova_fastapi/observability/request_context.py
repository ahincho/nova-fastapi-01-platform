"""
El middleware que abre el contexto de cada petición (ADR-037).

Ningún endpoint tiene que acordarse de leer las cabeceras de correlación: así es
como un servicio termina con tres formas de hacerlo y una ruta que no hace
ninguna.
"""

import re
import uuid
from collections.abc import Sequence

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nova_fastapi.observability.context import bind_request_id, reset_request_id

# Lo que se acepta de afuera termina en los logs y en los cuerpos de error: corto
# y sin nada que pueda partir una línea ni ensuciar una consulta.
_VALID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def accepted_request_id(headers: dict[bytes, bytes], accept: Sequence[str]) -> str | None:
    """El id que trae la petición, en la primera cabecera de `accept` que lo tenga bien formado."""
    for name in accept:
        value = headers.get(name.lower().encode("latin-1"), b"").decode("latin-1").strip()
        if _VALID.match(value):
            return value
    return None


class RequestContextMiddleware:
    """
    Fija el id de la petición: el que trae en una de las cabeceras aceptadas o,
    si no trae ninguno, uno nuevo. Lo deja en el contexto, para que un error lo
    tome al nacer, y en `request.state.request_id`, para lo que corre fuera de
    este middleware. Con `echo`, lo devuelve en esa cabecera de la respuesta,
    con el nombre del borde: el llamador lo recibe como lo mandó.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        accept: Sequence[str] = ("x-request-id",),
        echo: str | None = "x-request-id",
    ) -> None:
        self.app = app
        self.accept = tuple(accept)
        self.echo = echo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = accepted_request_id(dict(scope["headers"]), self.accept) or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = bind_request_id(request_id)

        async def send_with_id(message: Message) -> None:
            if self.echo and message["type"] == "http.response.start":
                MutableHeaders(scope=message)[self.echo] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset_request_id(token)
