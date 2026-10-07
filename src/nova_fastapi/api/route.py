"""
La ruta de Nova: le da a lo que devuelve un endpoint la forma del estándar.

Un endpoint devuelve su objeto y nunca arma el sobre. La ruta decide qué pasa
por el estándar; cómo se ve lo decide el estándar. Además documenta en `/docs`
la respuesta como de verdad sale, con el sobre alrededor del modelo.
"""

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.responses import Response

from nova_fastapi.api_standard.standard import ApiStandard, NovaEnvelopeStandard

_SKIP = "__nova_skip_envelope__"
_ENVELOPED = "__nova_enveloped__"

# Los status que no llevan cuerpo: no hay nada que envolver.
_NO_BODY = {204, 205, 304}


def skip_envelope[F: Callable[..., Any]](endpoint: F) -> F:
    """
    Deja la respuesta de un endpoint como la devuelve: una sonda de salud que el
    hosting lee con su propia forma, una descarga, un webhook que exige su cuerpo.
    """
    setattr(endpoint, _SKIP, True)
    return endpoint


def _returns_response(payload_type: Any) -> bool:
    return inspect.isclass(payload_type) and issubclass(payload_type, Response)


def _envelope(
    endpoint: Callable[..., Any], standard: ApiStandard, status: int
) -> Callable[..., Any]:
    """
    El endpoint con su resultado dentro del estándar.

    Una `Response` que el endpoint arma él mismo, o un cuerpo que ya es del
    estándar, pasan tal cual: envolverlos daría `{ data: { data: ... } }`. El
    status del sobre es el que declara la ruta; un endpoint que contesta otro
    arma su propia respuesta.
    """

    def wrap(result: Any) -> Any:
        if isinstance(result, Response) or standard.owns(result):
            return result
        return standard.success(result, status)

    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def enveloped_async(*args: Any, **kwargs: Any) -> Any:
            return wrap(await endpoint(*args, **kwargs))

        enveloped: Callable[..., Any] = enveloped_async
    else:

        @functools.wraps(endpoint)
        def enveloped_sync(*args: Any, **kwargs: Any) -> Any:
            return wrap(endpoint(*args, **kwargs))

        enveloped = enveloped_sync

    setattr(enveloped, _ENVELOPED, True)
    return enveloped


class NovaRoute(APIRoute):
    """
    Una ruta cuyo éxito sale con el estándar de API, el sobre de Nova por defecto.

    Se usa como `route_class` de un router; `install_nova` la pone en el de la
    aplicación. Para combinarla con otra ruta propia, se hereda de las dos:

        class Route(NovaRoute, LimitedRoute): ...

    Un estándar propio para los éxitos se declara en una subclase:

        class UtpRoute(NovaRoute):
            standard = UtpStandard()
    """

    standard: ApiStandard = NovaEnvelopeStandard()

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        if self._wraps(endpoint, kwargs):
            declared = kwargs.get("response_model")
            payload_type = (
                inspect.signature(endpoint).return_annotation
                if declared is None or isinstance(declared, DefaultPlaceholder)
                else declared
            )
            if payload_type is inspect.Signature.empty:
                payload_type = Any
            status = kwargs.get("status_code") or 200
            kwargs["response_model"] = self.standard.success_model(payload_type)
            endpoint = _envelope(endpoint, self.standard, status)
        super().__init__(path, endpoint, **kwargs)

    @staticmethod
    def _wraps(endpoint: Callable[..., Any], kwargs: dict[str, Any]) -> bool:
        # Ya envuelto: FastAPI vuelve a crear la ruta al incluir un router en la
        # aplicación, con el endpoint que la primera ya envolvió.
        if getattr(endpoint, _ENVELOPED, False) or getattr(endpoint, _SKIP, False):
            return False
        if kwargs.get("status_code") in _NO_BODY:
            return False
        # Un `response_model=None` explícito dice que la respuesta no tiene modelo.
        if "response_model" in kwargs and kwargs["response_model"] is None:
            return False
        response_class = kwargs.get("response_class")
        if isinstance(response_class, DefaultPlaceholder):
            response_class = response_class.value
        if response_class is not None and not (
            inspect.isclass(response_class) and issubclass(response_class, JSONResponse)
        ):
            return False
        return not _returns_response(inspect.signature(endpoint).return_annotation)
