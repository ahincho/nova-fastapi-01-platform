"""
`install_health`: las sondas de Nova en una aplicación de FastAPI.

Es el equivalente de `NovaHealthModule.forRoot(...)` en NestJS, con su mismo
contrato (ADR-030): `GET <path>/live`, `GET <path>/ready` y, si se pide, la ruta
heredada, con el cuerpo de `@nestjs/terminus`.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from fastapi import FastAPI, params, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, APIRouter
from pydantic import BaseModel

from nova_fastapi.health.checks import (
    DEFAULT_CHECK_TIMEOUT,
    HealthReport,
    ReadinessCheck,
    run_readiness,
)

DEFAULT_PATH = "health"


class CheckDetail(BaseModel):
    status: Literal["up", "down"]
    message: str | None = None


class HealthBody(BaseModel):
    """El cuerpo de las sondas, el mismo que devuelve `nova-nestjs`."""

    status: Literal["ok", "error"]
    info: dict[str, CheckDetail]
    error: dict[str, CheckDetail]
    details: dict[str, CheckDetail]


_READY_RESPONSES = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": HealthBody,
        "description": "Algún chequeo falló o no contestó a tiempo. La causa queda en el log.",
    }
}


def _route(path: str) -> str:
    return "/" + path.strip("/")


def install_health(
    app: FastAPI,
    *,
    path: str = DEFAULT_PATH,
    legacy_path: str | None = None,
    readiness_checks: Sequence[ReadinessCheck] = (),
    check_timeout: float = DEFAULT_CHECK_TIMEOUT,
    dependencies: Sequence[params.Depends] = (),
    responses: Mapping[int | str, dict[str, Any]] | None = None,
    tags: Sequence[str] = ("health",),
) -> APIRouter:
    """
    Sirve las sondas en `app` y devuelve su router.

    - `live` responde sin tocar ninguna dependencia: una sonda de vida que cae
      porque la base está caída consigue que reinicien el proceso, y eso no
      levanta la base.
    - `ready` corre `readiness_checks` en paralelo, cada uno con
      `check_timeout` segundos, y responde 503 si alguno falla. Sin chequeos,
      el servicio está listo en cuanto escucha.
    - `legacy_path` es la ruta que un balanceador ya revisa, por ejemplo
      `api/v1/health`. Responde como `ready`: decide si llega tráfico, así que
      tiene que caer con los chequeos.

    `dependencies` se suma a `ready` y a la ruta heredada, nunca a `live`: es el
    lugar de un límite de peticiones, y un 429 en la sonda de vida haría dar por
    caído un proceso sano. `responses` documenta en las mismas rutas lo que esas
    dependencias pueden responder, como ese 429.

    Las sondas no pasan por el sobre ni por el manejo de errores de Nova: el
    balanceador revisa la forma del cuerpo tanto como el código, así que el 503
    sale con el cuerpo de la sonda y no como un error. Mover `path` es mover lo
    que revisa el balanceador.
    """
    checks = tuple(readiness_checks)
    names = [check.name for check in checks]
    if len(set(names)) != len(names):
        raise ValueError(f"Cada chequeo necesita un nombre propio: {names}")
    if check_timeout <= 0:
        raise ValueError("check_timeout tiene que ser mayor que cero")

    async def live() -> JSONResponse:
        return JSONResponse(HealthReport().body())

    async def ready() -> JSONResponse:
        report = await run_readiness(checks, check_timeout)
        code = status.HTTP_200_OK if report.ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(report.body(), status_code=code)

    # APIRoute y no la ruta de la aplicación: con `install_nova` sería NovaRoute,
    # y la sonda no lleva sobre.
    guarded = {**_READY_RESPONSES, **(responses or {})}
    router = APIRouter(route_class=APIRoute, tags=list(tags))
    base = _route(path)
    router.add_api_route(
        f"{base}/live",
        live,
        methods=["GET"],
        response_model=HealthBody,
        summary="Si el proceso está vivo (liveness)",
        response_description="El proceso responde. No dice nada de sus dependencias.",
        operation_id="health_live",
    )
    router.add_api_route(
        f"{base}/ready",
        ready,
        methods=["GET"],
        response_model=HealthBody,
        responses=guarded,
        dependencies=list(dependencies),
        summary="Si el servicio puede recibir tráfico (readiness)",
        response_description="Todos los chequeos están arriba.",
        operation_id="health_ready",
    )
    if legacy_path:
        router.add_api_route(
            _route(legacy_path),
            ready,
            methods=["GET"],
            response_model=HealthBody,
            responses=guarded,
            dependencies=list(dependencies),
            summary="La ruta heredada, igual que readiness",
            response_description="Todos los chequeos están arriba.",
            operation_id="health_legacy",
        )
    app.include_router(router)
    return router
