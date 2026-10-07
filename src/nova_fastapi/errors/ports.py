"""
Los tres puertos de ADR-031, con su implementación por defecto en Nova.

El módulo define el modelo y estos contratos; una organización pone los suyos
en su perfil sin forkear la plataforma.

Ningún puerto recibe el error tal como nació. El proveedor que falló, la causa
y el mensaje real de una falla van al log, que el núcleo escribe antes de
llamar a cualquiera de ellos (ADR-034): un puerto propio no puede romper la
regla de que un 5xx nunca revela al proveedor, porque no tiene de dónde
sacarlo.
"""

from dataclasses import dataclass
from typing import Protocol

from nova_fastapi.errors.failure import ApiFailure, ApiFailureKind, ApiWire
from nova_fastapi.errors.layer import ErrorType, Layer
from nova_fastapi.errors.nova_error import FieldError


@dataclass(frozen=True)
class ErrorDescription:
    """Lo que ve el cliente de un error: su código y su mensaje."""

    code: str
    message: str


@dataclass(frozen=True)
class ErrorClassification:
    """
    Lo que `ErrorStatusMapper` ve de un error: cómo está clasificado y su código
    propio, por si una organización decide el status de un código en particular.
    Ni el proveedor, ni la causa, ni el mensaje.
    """

    layer: Layer
    type: ErrorType
    code: str | None = None


@dataclass(frozen=True)
class SanitizedError:
    """
    Lo que `ErrorCatalog` ve de un fallo, ya saneado por el núcleo.

    En un 5xx el núcleo quita `code`, `message` y `field_errors`, y el catálogo
    pone su código y su mensaje genérico. `type` falta solo en una excepción
    del framework cuyo status no tiene fila en la tabla.
    """

    kind: ApiFailureKind
    layer: Layer
    type: ErrorType | None
    code: str | None
    message: str | None
    field_errors: tuple[FieldError, ...]


class ErrorStatusMapper(Protocol):
    """
    Decide el HTTP de cada capa y tipo. Solo se consulta para los errores de
    Nova: una excepción del framework ya trae su status, y se respeta.
    """

    def status_of(self, error: ErrorClassification) -> int: ...


class ErrorCatalog(Protocol):
    """
    Decide el código y el mensaje que ve el cliente.

    Recibe el status ya decidido porque la regla depende de él: un 5xx nunca
    muestra el código propio ni el mensaje del error.
    """

    def describe(self, error: SanitizedError, status: int) -> ErrorDescription: ...


class ErrorSerializer(Protocol):
    """
    Decide el cuerpo y las cabeceras de una respuesta de error. Sirve para
    cambiar solo la forma de los errores, como RFC 9457, sin escribir un
    estándar entero.
    """

    def serialize(self, failure: ApiFailure) -> ApiWire: ...
