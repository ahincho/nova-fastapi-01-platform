"""
Un fallo ya clasificado y saneado, y lo que sale por el cable.

Es lo único que reciben el estándar de API (`nova_fastapi.api_standard`) y el
serializador de errores para
escribir una respuesta de error, y sobre eso se apoya el reparto de ADR-034:
el estándar decide la forma del cuerpo, pero no tiene de dónde sacar lo que el
núcleo le quitó. No trae el proveedor que falló ni la causa: esos van al log.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from nova_fastapi.errors.layer import Layer

type ApiFailureKind = Literal["validation", "request", "internal"]
"""
Por qué falló una petición, en los términos que el núcleo puede afirmar: la
entrada no pasó la validación, el llamador pidió algo que no corresponde (un
4xx) o el fallo es nuestro (un 5xx, o algo que ni siquiera era HTTP).
"""


@dataclass(frozen=True)
class ApiFailureItem:
    """
    Un error dentro de un fallo. `field` es None cuando no es de un campo.

    `code` lo pone siempre el núcleo: el propio de quien lanzó en un 4xx, o el
    que decide el catálogo. Es None solo cuando alguien llama al estándar a
    mano, y entonces el estándar pone el suyo. `message` ya está saneado: en un
    5xx es el genérico.
    """

    code: str | None
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ApiFailure:
    """
    Un fallo listo para escribirse.

    `layer` le dice a un estándar propio si fue un rechazo esperado o un
    incidente, sin decirle qué falló por dentro. `trace_id` es el que se puede
    citar al reportarlo. `retry_after`, en segundos, sale como `Retry-After`.
    """

    status: int
    kind: ApiFailureKind
    layer: Layer
    trace_id: str | None
    retry_after: int | None
    errors: tuple[ApiFailureItem, ...]


@dataclass(frozen=True)
class ApiWire:
    """
    El cuerpo y las cabeceras de una respuesta.

    `content_type` None deja `application/json`; un estándar como RFC 9457 pone
    `application/problem+json`.
    """

    body: Any
    content_type: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
