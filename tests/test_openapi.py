"""Los errores en `/docs`, con el sobre y no con el 422 de FastAPI."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from nova_fastapi import error_responses, install_nova
from nova_fastapi.api.openapi import VALIDATION_DESCRIPTION, document
from nova_fastapi.api_standard import NovaEnvelopeStandard


class Body(BaseModel):
    name: str


def _app() -> FastAPI:
    app = FastAPI()
    install_nova(app)

    @app.post("/with-input", responses=error_responses(404, 409))
    def with_input(body: Body) -> dict:
        return {}

    @app.get("/without-input")
    def without_input() -> dict:
        return {}

    return app


def _schema() -> dict:
    return TestClient(_app()).get("/openapi.json").json()


def test_the_validation_failure_is_documented_as_the_400_it_is():
    responses = _schema()["paths"]["/with-input"]["post"]["responses"]

    assert "422" not in responses
    assert responses["400"]["description"] == VALIDATION_DESCRIPTION
    assert "allOf" in responses["400"]["content"]["application/json"]["schema"]


def test_an_endpoint_without_input_does_not_get_a_validation_failure():
    responses = _schema()["paths"]["/without-input"]["get"]["responses"]

    assert "400" not in responses


def test_the_failures_an_endpoint_declares_carry_the_envelope_and_the_message_of_the_catalog():
    responses = _schema()["paths"]["/with-input"]["post"]["responses"]

    assert responses["404"]["description"] == "El recurso no existe"
    assert responses["409"]["content"]["application/json"]["schema"]["allOf"][0] == {
        "$ref": "#/components/schemas/ApiEnvelope"
    }


def test_the_schemas_of_fastapis_422_are_gone_and_the_envelope_is_there():
    schemas = _schema()["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert {"ApiEnvelope", "ApiErrorItem", "ApiMetadata"} <= set(schemas)
    assert "traceId" in schemas["ApiMetadata"]["properties"]


def test_documenting_twice_changes_nothing():
    app = _app()
    once = app.openapi()

    assert document(once, NovaEnvelopeStandard()) == once
