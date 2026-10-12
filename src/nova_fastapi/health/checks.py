"""
Los chequeos de disponibilidad y su corrida, sin el framework.

El resultado tiene la forma del cuerpo de las sondas de Nova, la de
`@nestjs/terminus` que devuelve `nova-nestjs`: un servicio de FastAPI y uno de
NestJS responden igual a su balanceador (ADR-030).
"""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("nova_fastapi.health")

# Un chequeo sin fecha límite puede colgar la sonda, y una sonda que nunca
# contesta es peor que una que dice "no estoy lista": el balanceador espera su
# propio timeout en cada intento.
DEFAULT_CHECK_TIMEOUT = 2.0

NOT_READY = "reported not ready"
# Lo que dice el cuerpo cuando un chequeo lanza. La sonda es pública y el
# mensaje de un driver puede nombrar un host o un usuario: la causa va al log.
FAILED = "check failed"


@dataclass(frozen=True)
class ReadinessCheck:
    """
    Una cosa de la que depende estar listo.

    Devolver un valor falso y lanzar significan lo mismo para la sonda: un
    chequeo no tiene que protegerse solo. `check` puede ser una corrutina o una
    función; una función corre en un hilo para no frenar el loop, y si devuelve
    algo esperable, se espera.
    """

    name: str
    check: Callable[[], bool | Awaitable[bool]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    up: bool
    message: str | None = None
    # Solo para el log: el porqué que no puede salir en el cuerpo.
    reason: str | None = None

    def detail(self) -> dict[str, str]:
        if self.up:
            return {"status": "up"}
        return {"status": "down", "message": self.message or NOT_READY}


@dataclass(frozen=True)
class HealthReport:
    results: tuple[CheckResult, ...] = ()

    @property
    def ok(self) -> bool:
        return all(result.up for result in self.results)

    def body(self) -> dict[str, Any]:
        """El cuerpo de la sonda: `info` los que están arriba, `error` los caídos, `details` todos."""
        return {
            "status": "ok" if self.ok else "error",
            "info": {r.name: r.detail() for r in self.results if r.up},
            "error": {r.name: r.detail() for r in self.results if not r.up},
            "details": {r.name: r.detail() for r in self.results},
        }


async def _call(check: ReadinessCheck) -> Any:
    if inspect.iscoroutinefunction(check.check):
        return await check.check()
    result = await asyncio.to_thread(check.check)
    if inspect.isawaitable(result):
        return await result
    return result


async def _run(check: ReadinessCheck, timeout: float) -> CheckResult:
    try:
        async with asyncio.timeout(timeout):
            ready = await _call(check)
    except TimeoutError:
        message = f"timed out after {timeout:g}s"
        return CheckResult(check.name, up=False, message=message, reason=message)
    except Exception as e:
        return CheckResult(check.name, up=False, message=FAILED, reason=f"{type(e).__name__}: {e}")
    if ready:
        return CheckResult(check.name, up=True)
    return CheckResult(check.name, up=False, message=NOT_READY, reason=NOT_READY)


async def run_readiness(
    checks: Sequence[ReadinessCheck], timeout: float = DEFAULT_CHECK_TIMEOUT
) -> HealthReport:
    """
    Corre los chequeos en paralelo, cada uno con su fecha límite.

    Deja un warn por cada chequeo caído, con el chequeo y su motivo como campos:
    así se pueden contar las caídas de uno sin parsear texto, y una dependencia
    que parpadea se ve sin que cada ciclo de la sonda parezca un error.
    """
    results = await asyncio.gather(*(_run(check, timeout) for check in checks))
    for result in results:
        if not result.up:
            logger.warning(
                "Readiness check failed",
                extra={"readiness": {"check": result.name, "message": result.reason}},
            )
    return HealthReport(tuple(results))
