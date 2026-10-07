"""El núcleo sin framework: el modelo de errores, el catálogo, el perfil."""

import math
import subprocess
import sys
from pathlib import Path

import pytest

from nova_fastapi import ApplicationError, InfrastructureError, Profile
from nova_fastapi.api.profile import NovaConfig
from nova_fastapi.errors import (
    ErrorCodes,
    Layer,
    NovaErrorCatalog,
    NovaErrorStatusMapper,
    SanitizedError,
)
from nova_fastapi.errors.status_mapper import STATUS_BY_LAYER

REPO = Path(__file__).resolve().parents[1]


def test_the_core_does_not_load_any_framework():
    """
    El mismo caso de uso corre detrás de HTTP o de un consumidor de cola. Corre
    en un proceso aparte porque en este las otras pruebas ya cargaron FastAPI.
    """
    code = (
        "import sys, nova_fastapi.errors, nova_fastapi.api_standard; "
        "print(' '.join(sorted({m.split('.')[0] for m in sys.modules})))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO
    ).stdout.split()

    assert [name for name in loaded if name in ("fastapi", "starlette")] == []


@pytest.mark.parametrize(
    ("given", "expected"), [(1.2, 2), (30, 30), (0, 0), (-5, None), (math.inf, None), (None, None)]
)
def test_retry_after_is_whole_seconds_rounded_up_and_a_bad_value_is_dropped(given, expected):
    assert ApplicationError.rate_limited("Espera", retry_after=given).retry_after == expected


def test_an_infrastructure_error_writes_a_log_message_with_its_provider():
    error = InfrastructureError.timeout("gemini")

    assert error.layer is Layer.INFRASTRUCTURE
    assert error.upstream == "gemini"
    assert error.message == "Upstream gemini did not respond in time"


def test_every_type_of_every_layer_has_its_status():
    statuses = {status for table in STATUS_BY_LAYER.values() for status in table.values()}

    assert statuses == {400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 504}


def test_the_catalog_names_what_its_table_does_not():
    catalog = NovaErrorCatalog()
    expected = SanitizedError(
        kind="request", layer=Layer.APPLICATION, type=None, code=None, message=None, field_errors=()
    )

    assert catalog.describe(expected, 418).code == "REQUEST_ERROR"
    assert catalog.describe(expected, 418).message == "La solicitud no se pudo atender"
    assert catalog.describe(expected, 507).code == "INTERNAL_SERVER_ERROR"


def test_the_catalog_never_shows_an_own_code_or_message_in_a_5xx():
    sanitized = SanitizedError(
        kind="internal",
        layer=Layer.PLATFORM,
        type=None,
        code="OWN",
        message="secreto",
        field_errors=(),
    )

    description = NovaErrorCatalog().describe(sanitized, 500)

    assert (description.code, description.message) == (
        "INTERNAL_SERVER_ERROR",
        "Error interno del servidor",
    )


def test_own_codes_add_to_the_ones_of_nova_instead_of_replacing_them():
    codes = ErrorCodes(by_status={409: "ALREADY_EXISTS"})

    assert codes.code_for(409, "request") == "ALREADY_EXISTS"
    assert codes.code_for(404, "request") == "NOT_FOUND"


def test_a_status_mapper_of_nova_sends_an_unknown_type_to_500():
    from nova_fastapi.errors import ErrorClassification

    assert NovaErrorStatusMapper().status_of(ErrorClassification(Layer.DOMAIN, "OTRO")) == 500  # type: ignore[arg-type]


def test_the_service_wins_over_the_profile_and_the_profile_over_nova():
    profile = Profile(
        name="utp", request_id_echo="transaction-id", internal_error_message="Del perfil"
    )

    config = NovaConfig().merged(profile, internal_error_message="Del servicio")

    assert config.profile == "utp"
    assert config.request_id_echo == "transaction-id"
    assert config.internal_error_message == "Del servicio"
    assert config.request_id_accept == ("x-request-id",)
