"""
El perfil de una organización y la configuración que resulta (ADR-036).

Lo que una organización comparte entre sus servicios se declara una vez, en su
perfil, y un servicio lo activa al instalar Nova. El orden es siempre el mismo:
lo de Nova, encima lo del perfil, y encima lo que declara el servicio.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from nova_fastapi.api_standard.standard import ApiStandard, NovaEnvelopeStandard
from nova_fastapi.errors.ports import ErrorCatalog, ErrorSerializer, ErrorStatusMapper
from nova_fastapi.errors.status_mapper import NovaErrorStatusMapper


@dataclass(frozen=True)
class Profile:
    """
    Lo que una organización fija para todos sus servicios. Lo que queda en None
    deja el valor de Nova.

        UTP = Profile(
            name="utp",
            request_id_accept=("transaction-id", "x-request-id"),
            catalog=UtpErrorCatalog(),
        )
    """

    name: str
    request_id_accept: Sequence[str] | None = None
    request_id_echo: str | None = None
    standard: ApiStandard | None = None
    status_mapper: ErrorStatusMapper | None = None
    catalog: ErrorCatalog | None = None
    serializer: ErrorSerializer | None = None
    internal_error_message: str | None = None


@dataclass(frozen=True)
class NovaConfig:
    """
    La configuración ya resuelta con la que corre un servicio.

    `catalog` y `serializer` en None dejan los del estándar activo: un servicio
    que solo cambia el estándar no tiene que repetir su catálogo.
    """

    profile: str | None = None
    request_id_accept: tuple[str, ...] = ("x-request-id",)
    request_id_echo: str | None = "x-request-id"
    standard: ApiStandard = field(default_factory=NovaEnvelopeStandard)
    status_mapper: ErrorStatusMapper = field(default_factory=NovaErrorStatusMapper)
    catalog: ErrorCatalog | None = None
    serializer: ErrorSerializer | None = None
    internal_error_message: str | None = None

    def merged(self, profile: Profile | None, **overrides: object) -> "NovaConfig":
        """Esta configuración, con el perfil encima y lo del servicio encima de todo."""
        config = self
        if profile is not None:
            config = replace(
                config,
                profile=profile.name,
                **{
                    name: tuple(value) if name == "request_id_accept" else value
                    for name, value in vars(profile).items()
                    if name != "name" and value is not None
                },
            )
        given = {name: value for name, value in overrides.items() if value is not None}
        if "request_id_accept" in given:
            given["request_id_accept"] = tuple(given["request_id_accept"])  # type: ignore[arg-type]
        return replace(config, **given)  # type: ignore[arg-type]
