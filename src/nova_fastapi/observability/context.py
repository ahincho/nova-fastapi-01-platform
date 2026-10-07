"""
El id de la petición en curso, para quien lo necesite sin recibirlo.

Lo escribe el middleware de correlación al abrir cada petición y lo lee un
error de Nova al nacer (ADR-031): para cuando el error se responde, el contexto
se puede haber perdido. Es una variable de contexto, así que cada petición ve
la suya aunque corran varias a la vez en el mismo hilo.

No importa ningún framework: un error se construye igual detrás de HTTP o de
un consumidor de cola, y fuera de una petición el id simplemente no está.
"""

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("nova_request_id", default=None)


def current_request_id() -> str | None:
    """El id de la petición en curso, o None fuera de una."""
    return _request_id.get()


def bind_request_id(request_id: str) -> Token[str | None]:
    """Fija el id de la petición en curso. Devuelve con qué restaurar el anterior."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restaura el id que había antes de `bind_request_id`."""
    _request_id.reset(token)
