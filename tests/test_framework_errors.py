"""Las excepciones de FastAPI y Starlette, leídas por su status (ADR-031)."""

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from nova_fastapi import DomainError, PlatformError, install_nova


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(max_length=2)
    headline: str = Field(max_length=10)


class Out(BaseModel):
    id: int


def _client(**options) -> TestClient:
    app = FastAPI()
    install_nova(app, **options)

    @app.get("/auth")
    def auth() -> None:
        raise HTTPException(
            401, "Inicia sesión para continuar.", headers={"WWW-Authenticate": "Bearer"}
        )

    @app.get("/plain-forbidden")
    def plain_forbidden() -> None:
        raise HTTPException(403)

    @app.get("/coded")
    def coded() -> None:
        error = HTTPException(402, "No te alcanzan las monedas.")
        error.error_code = "INSUFFICIENT_COINS"  # type: ignore[attr-defined]
        raise error

    @app.get("/framework-503")
    def framework_503() -> None:
        raise HTTPException(503, "El servidor de Supabase no responde")

    @app.post("/profile")
    def profile(body: Body, city: str = Query(max_length=5)) -> None:
        return None

    @app.get("/bad-response", response_model=Out)
    def bad_response() -> dict:
        return {"id": "no es un número"}

    @app.get("/domain")
    def domain() -> None:
        raise DomainError.not_found("Pedido no encontrado")

    @app.get("/platform")
    def platform() -> None:
        raise PlatformError.internal("la cola se llenó", cause=ValueError("detalle"))

    return TestClient(app, raise_server_exceptions=False)


def test_a_framework_exception_keeps_its_status_its_text_and_its_headers():
    r = _client().get("/auth")

    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert r.json()["errors"] == [
        {"code": "UNAUTHORIZED", "message": "Inicia sesión para continuar.", "field": None}
    ]


def test_a_framework_exception_without_its_own_text_gets_the_one_of_the_catalog():
    r = _client().get("/plain-forbidden")

    assert r.json()["errors"][0]["message"] == "No hay permiso para esta operación"


def test_a_framework_exception_can_carry_its_own_code():
    r = _client().get("/coded")

    assert r.status_code == 402
    assert r.json()["errors"][0]["code"] == "INSUFFICIENT_COINS"


def test_a_framework_5xx_never_shows_what_it_said():
    r = _client().get("/framework-503")

    assert r.status_code == 503
    assert r.json()["errors"][0]["code"] == "SERVICE_UNAVAILABLE"
    assert "Supabase" not in r.text


def test_a_route_that_does_not_exist_and_a_method_that_does_not_fit():
    client = _client()

    assert client.get("/no-existe").json()["errors"][0]["code"] == "NOT_FOUND"
    r = client.delete("/auth")
    assert r.status_code == 405
    assert r.json()["errors"][0]["code"] == "METHOD_NOT_ALLOWED"


def test_a_validation_failure_is_a_400_with_one_entry_per_field_in_spanish():
    r = _client().post(
        "/profile",
        params={"city": "Arequipa"},
        json={"skills": ["a", "b", "c"], "name": "Quispe"},
    )

    assert r.status_code == 400
    errors = {error["field"]: error for error in r.json()["errors"]}
    assert set(errors) == {"skills", "headline", "name", "city"}
    assert {error["code"] for error in errors.values()} == {"BAD_REQUEST"}
    assert errors["skills"]["message"] == "Puede tener hasta 2 elementos"
    assert errors["headline"]["message"] == "Falta este dato"
    assert errors["name"]["message"] == "Este dato no se acepta"
    assert errors["city"]["message"] == "Puede tener hasta 5 caracteres"


def test_a_validation_failure_never_repeats_what_was_sent():
    r = _client().post(
        "/profile", params={"city": "Lima"}, json={"skills": [], "headline": "Quispe Mamani Ccori"}
    )

    assert "Quispe" not in r.text


def test_a_response_that_does_not_fit_its_model_is_our_fault():
    r = _client().get("/bad-response")

    assert r.status_code == 500
    assert r.json()["errors"][0]["code"] == "INTERNAL_SERVER_ERROR"


def test_an_expected_error_is_a_warning_without_the_stack(caplog):
    with caplog.at_level(logging.WARNING, logger="nova_fastapi.errors"):
        _client().get("/domain")

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert record.nova["layer"] == "domain"
    assert record.nova["code"] == "NOT_FOUND"
    assert record.nova["traceId"]


def test_an_incident_is_an_error_with_its_cause(caplog):
    with caplog.at_level(logging.WARNING, logger="nova_fastapi.errors"):
        _client().get("/platform")

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert record.getMessage() == "la cola se llenó"
    assert record.nova["layer"] == "platform"


def test_a_5xx_message_can_be_changed_for_the_whole_service():
    r = _client(internal_error_message="Algo falló de nuestro lado.").get("/platform")

    assert r.json()["errors"][0]["message"] == "Algo falló de nuestro lado."


def test_an_unexpected_error_goes_out_with_the_headers_of_the_middlewares_added_later():
    """Un 500 que respondiera Starlette por fuera de CORS no se podría leer desde el navegador."""
    app = FastAPI()
    install_nova(app)
    app.add_middleware(CORSMiddleware, allow_origins=["https://web.example"])

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("se cayó")

    r = TestClient(app, raise_server_exceptions=False).get(
        "/crash", headers={"Origin": "https://web.example"}
    )

    assert r.status_code == 500
    assert r.headers["access-control-allow-origin"] == "https://web.example"
    assert r.json()["errors"][0]["code"] == "INTERNAL_SERVER_ERROR"
