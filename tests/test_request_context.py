"""El id de cada petición (ADR-037): aceptado, generado, devuelto y citado."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_fastapi import DomainError, Profile, install_nova
from nova_fastapi.observability.context import current_request_id


def _client(**options) -> TestClient:
    app = FastAPI()
    install_nova(app, **options)

    @app.get("/ok")
    def ok() -> dict:
        return {"id": current_request_id()}

    @app.get("/fail")
    def fail() -> None:
        raise DomainError.not_found("No existe")

    return TestClient(app)


def test_every_response_echoes_an_id():
    r = _client().get("/ok")

    assert r.headers["x-request-id"]
    assert r.json()["data"]["id"] == r.headers["x-request-id"]


def test_two_requests_never_share_an_id():
    client = _client()

    assert client.get("/ok").headers["x-request-id"] != client.get("/ok").headers["x-request-id"]


def test_an_id_the_caller_sent_is_kept():
    r = _client().get("/ok", headers={"x-request-id": "proxy-abc-123"})

    assert r.headers["x-request-id"] == "proxy-abc-123"


@pytest.mark.parametrize("received", ["con espacios", "x" * 129, "salto\\nde-linea", ""])
def test_an_id_with_a_strange_shape_is_replaced(received):
    """Lo que se acepta de afuera termina en los logs: tiene que ser corto y limpio."""
    r = _client().get("/ok", headers={"x-request-id": received})

    assert r.headers["x-request-id"] != received


def test_the_error_cites_the_id_of_its_request():
    r = _client().get("/fail", headers={"x-request-id": "error-de-prueba"})

    assert r.json()["metadata"]["traceId"] == "error-de-prueba"


def test_a_profile_decides_which_headers_are_accepted_and_which_one_echoes():
    utp = Profile(
        name="utp",
        request_id_accept=("transaction-id", "x-request-id"),
        request_id_echo="transaction-id",
    )

    r = _client(profile=utp).get("/ok", headers={"transaction-id": "tx-1"})

    assert r.headers["transaction-id"] == "tx-1"
    assert "x-request-id" not in r.headers


def test_outside_a_request_there_is_no_id():
    assert current_request_id() is None
    assert DomainError.not_found("No existe").trace_id is None
