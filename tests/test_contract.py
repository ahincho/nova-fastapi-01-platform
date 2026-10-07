"""
La suite de contrato de ADR-031: los mismos nueve casos que corren Spring Boot,
Quarkus y NestJS. Si un caso cambia aquí, cambia para todos los stacks.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_fastapi import (
    ApplicationError,
    DomainError,
    FieldError,
    InfrastructureError,
    install_nova,
)
from nova_fastapi.errors import ErrorCatalog, ErrorDescription, SanitizedError


class _OwnCatalog:
    """Un catálogo propio, como el que traería el perfil de una organización."""

    def describe(self, error: SanitizedError, status: int) -> ErrorDescription:
        return ErrorDescription(code=f"UTP_{status}", message="Mensaje de la organización")


def _app(catalog: ErrorCatalog | None = None) -> FastAPI:
    app = FastAPI()
    install_nova(app, catalog=catalog)

    @app.get("/not-found")
    def not_found() -> None:
        raise DomainError.not_found("Pedido no encontrado", code="ORDER_NOT_FOUND")

    @app.get("/domain-conflict")
    def domain_conflict() -> None:
        raise DomainError.conflict("El pedido ya está cancelado")

    @app.get("/invalid-input")
    def invalid_input() -> None:
        raise ApplicationError.invalid_input(
            "La inscripción no es válida",
            [FieldError("period_id", "Debe ser un entero"), FieldError("email", "Falta el correo")],
        )

    @app.get("/application-conflict")
    def application_conflict() -> None:
        raise ApplicationError.conflict("Otra operación está en curso", retry_after=1)

    @app.get("/rate-limited")
    def rate_limited() -> None:
        raise ApplicationError.rate_limited("Demasiadas solicitudes", retry_after=30)

    @app.get("/timeout")
    def timeout() -> None:
        raise InfrastructureError.timeout("academic-orchestrator")

    @app.get("/unavailable")
    def unavailable() -> None:
        raise InfrastructureError.unavailable("payments")

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("se cayó con la clave sk-123")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def _assert_envelope(body: dict, status: int) -> None:
    """Lo que vale para todos los casos: `success`, `status` y `metadata.traceId`."""
    assert body["success"] is False
    assert body["status"] == status
    assert body["data"] is None
    assert body["metadata"]["traceId"]


@pytest.mark.parametrize(
    ("path", "status", "code", "message"),
    [
        ("/not-found", 404, "ORDER_NOT_FOUND", "Pedido no encontrado"),
        ("/domain-conflict", 409, "CONFLICT", "El pedido ya está cancelado"),
        (
            "/unavailable",
            503,
            "SERVICE_UNAVAILABLE",
            "El servicio no está disponible en este momento",
        ),
        ("/crash", 500, "INTERNAL_SERVER_ERROR", "Error interno del servidor"),
    ],
    ids=[
        "not-found-con-código-propio",
        "conflict-sin-código",
        "unavailable",
        "excepción-cualquiera",
    ],
)
def test_a_single_error(client, path, status, code, message):
    r = client.get(path)

    assert r.status_code == status
    _assert_envelope(r.json(), status)
    assert r.json()["errors"] == [{"code": code, "message": message, "field": None}]


def test_invalid_input_has_one_entry_per_field(client):
    r = client.get("/invalid-input")

    assert r.status_code == 400
    _assert_envelope(r.json(), 400)
    assert r.json()["errors"] == [
        {"code": "BAD_REQUEST", "message": "Debe ser un entero", "field": "period_id"},
        {"code": "BAD_REQUEST", "message": "Falta el correo", "field": "email"},
    ]


@pytest.mark.parametrize(
    ("path", "status", "code", "retry_after"),
    [
        ("/application-conflict", 409, "CONFLICT", "1"),
        ("/rate-limited", 429, "TOO_MANY_REQUESTS", "30"),
    ],
)
def test_what_can_be_retried_says_when(client, path, status, code, retry_after):
    r = client.get(path)

    assert r.status_code == status
    _assert_envelope(r.json(), status)
    assert r.json()["errors"][0]["code"] == code
    assert r.headers["Retry-After"] == retry_after


def test_a_timeout_names_the_provider_in_the_log_but_not_in_the_body(client, caplog):
    with caplog.at_level(logging.ERROR, logger="nova_fastapi.errors"):
        r = client.get("/timeout")

    assert r.status_code == 504
    _assert_envelope(r.json(), 504)
    assert r.json()["errors"][0]["code"] == "GATEWAY_TIMEOUT"
    assert "academic-orchestrator" not in r.text
    [record] = [r for r in caplog.records if r.name == "nova_fastapi.errors"]
    assert record.nova["upstream"] == {"upstream": "academic-orchestrator"}


def test_an_own_catalog_replaces_the_one_of_nova():
    client = TestClient(_app(catalog=_OwnCatalog()), raise_server_exceptions=False)

    r = client.get("/not-found")

    assert r.status_code == 404
    assert r.json()["errors"] == [
        {"code": "UTP_404", "message": "Mensaje de la organización", "field": None}
    ]


def test_an_unexpected_error_never_reaches_the_client(client):
    r = client.get("/crash")

    assert "sk-123" not in r.text
    assert "RuntimeError" not in r.text
