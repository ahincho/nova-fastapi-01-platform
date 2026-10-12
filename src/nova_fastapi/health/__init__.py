"""
Las sondas de vida y de disponibilidad de Nova.

    from nova_fastapi.health import ReadinessCheck, install_health

    install_health(app, readiness_checks=[ReadinessCheck("database", ping)])

Los chequeos y su corrida (`nova_fastapi.health.checks`) no importan FastAPI.
"""

from typing import TYPE_CHECKING

from nova_fastapi.health.checks import (
    DEFAULT_CHECK_TIMEOUT,
    CheckResult,
    HealthReport,
    ReadinessCheck,
    run_readiness,
)

if TYPE_CHECKING:
    from nova_fastapi.health.install import HealthBody, install_health

__all__ = [
    "DEFAULT_CHECK_TIMEOUT",
    "CheckResult",
    "HealthBody",
    "HealthReport",
    "ReadinessCheck",
    "install_health",
    "run_readiness",
]


def __getattr__(name: str) -> object:
    # Como en el paquete raíz: el conector carga FastAPI recién cuando se pide.
    if name in {"HealthBody", "install_health"}:
        from nova_fastapi.health import install

        return getattr(install, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
