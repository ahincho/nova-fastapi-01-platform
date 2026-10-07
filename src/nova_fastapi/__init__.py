"""
Nova Platform para FastAPI.

    from fastapi import FastAPI
    from nova_fastapi import install_nova

    app = FastAPI()
    install_nova(app)

El modelo de errores (`nova_fastapi.errors`) y el sobre (`nova_fastapi.api_standard`)
no importan FastAPI: se usan igual en un consumidor de cola o en un script.
"""

from typing import TYPE_CHECKING

from nova_fastapi.errors import (
    ApplicationError,
    DomainError,
    FieldError,
    InfrastructureError,
    NovaError,
    PlatformError,
)

if TYPE_CHECKING:
    from nova_fastapi.api import NovaRoute, Profile, error_responses, install_nova, skip_envelope

__all__ = [
    "ApplicationError",
    "DomainError",
    "FieldError",
    "InfrastructureError",
    "NovaError",
    "NovaRoute",
    "PlatformError",
    "Profile",
    "error_responses",
    "install_nova",
    "skip_envelope",
]

_CONNECTOR = {"NovaRoute", "Profile", "error_responses", "install_nova", "skip_envelope"}


def __getattr__(name: str) -> object:
    # El conector importa FastAPI. Se carga recién cuando alguien lo pide, para
    # que usar los errores de Nova -desde un consumidor de cola, por ejemplo- no
    # arrastre el framework.
    if name in _CONNECTOR:
        from nova_fastapi import api

        return getattr(api, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
