"""Las sondas de vida y de disponibilidad, con el contrato de nova-nestjs."""

import asyncio
import logging
import time

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from nova_fastapi import ReadinessCheck, install_health, install_nova
from nova_fastapi.health import run_readiness


def _client(**options) -> TestClient:
    app = FastAPI()
    install_nova(app)
    install_health(app, **options)
    return TestClient(app)


async def _up() -> bool:
    return True


async def _down() -> bool:
    return False


async def _boom() -> bool:
    raise ConnectionError("could not connect to db.internal:5432 as admin")


def test_live_answers_without_running_any_check():
    calls = []

    async def counted() -> bool:
        calls.append(1)
        return False

    response = _client(readiness_checks=[ReadinessCheck("database", counted)]).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "info": {}, "error": {}, "details": {}}
    assert calls == []


def test_ready_without_checks_is_ready():
    response = _client().get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_each_check_with_the_terminus_body():
    client = _client(
        readiness_checks=[ReadinessCheck("database", _up), ReadinessCheck("cache", _down)]
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "info": {"database": {"status": "up"}},
        "error": {"cache": {"status": "down", "message": "reported not ready"}},
        "details": {
            "database": {"status": "up"},
            "cache": {"status": "down", "message": "reported not ready"},
        },
    }


def test_the_probe_is_not_wrapped_in_the_nova_envelope():
    body = _client(readiness_checks=[ReadinessCheck("cache", _down)]).get("/health/ready").json()

    assert "success" not in body
    assert "errors" not in body


def test_a_check_that_raises_is_down_and_its_cause_goes_only_to_the_log(caplog):
    client = _client(readiness_checks=[ReadinessCheck("database", _boom)])

    with caplog.at_level(logging.WARNING, logger="nova_fastapi.health"):
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"] == {"database": {"status": "down", "message": "check failed"}}
    assert "db.internal" not in response.text
    [record] = [r for r in caplog.records if r.name == "nova_fastapi.health"]
    assert record.readiness["check"] == "database"
    assert "db.internal" in record.readiness["message"]


def test_a_check_that_does_not_answer_in_time_is_down():
    async def slow() -> bool:
        await asyncio.sleep(5)
        return True

    client = _client(readiness_checks=[ReadinessCheck("slow", slow)], check_timeout=0.05)

    started = time.monotonic()
    response = client.get("/health/ready")

    assert time.monotonic() - started < 2
    assert response.status_code == 503
    assert response.json()["error"]["slow"] == {
        "status": "down",
        "message": "timed out after 0.05s",
    }


def test_checks_run_in_parallel():
    async def nap() -> bool:
        await asyncio.sleep(0.3)
        return True

    checks = [ReadinessCheck(f"c{i}", nap) for i in range(5)]

    started = time.monotonic()
    report = asyncio.run(run_readiness(checks))

    assert report.ok
    assert time.monotonic() - started < 1


def test_a_sync_check_runs_and_can_return_an_awaitable():
    client = _client(
        readiness_checks=[
            ReadinessCheck("sync", lambda: True),
            ReadinessCheck("lambda", lambda: _up()),
        ]
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert set(response.json()["info"]) == {"sync", "lambda"}


def test_the_legacy_path_answers_like_ready():
    client = _client(legacy_path="api/v1/health", readiness_checks=[ReadinessCheck("cache", _down)])

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "cache": {"status": "down", "message": "reported not ready"}
    }


def test_the_path_can_move():
    client = _client(path="/api/health/")

    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/health/ready").status_code == 200
    assert client.get("/health/live").status_code == 404


def test_dependencies_guard_ready_and_legacy_but_never_live():
    def limited() -> None:
        raise HTTPException(status_code=429)

    client = _client(legacy_path="old", dependencies=[Depends(limited)])

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 429
    assert client.get("/old").status_code == 429


def test_two_checks_cannot_share_a_name():
    with pytest.raises(ValueError, match="nombre propio"):
        install_health(
            FastAPI(), readiness_checks=[ReadinessCheck("db", _up), ReadinessCheck("db", _up)]
        )


def test_the_timeout_must_be_positive():
    with pytest.raises(ValueError, match="mayor que cero"):
        install_health(FastAPI(), check_timeout=0)


def test_openapi_documents_the_probes_with_their_body():
    app = FastAPI()
    install_nova(app)
    install_health(app)

    paths = app.openapi()["paths"]

    assert set(paths) >= {"/health/live", "/health/ready"}
    assert "503" in paths["/health/ready"]["get"]["responses"]
