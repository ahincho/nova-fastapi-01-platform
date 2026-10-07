"""El éxito con el sobre de Nova, y lo que se deja pasar sin envolver."""

from fastapi import APIRouter, FastAPI, Response, status
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from nova_fastapi import NovaRoute, install_nova, skip_envelope
from nova_fastapi.api_standard import ok


class Course(BaseModel):
    id: int
    name: str


def _client() -> TestClient:
    app = FastAPI()
    install_nova(app)
    router = APIRouter(prefix="/courses", route_class=NovaRoute)

    @app.get("/plain")
    def plain() -> dict:
        return {"a": 1}

    @router.get("/{course_id}", response_model=Course)
    async def read(course_id: int) -> dict:
        return {"id": course_id, "name": "Álgebra", "internal": "no sale"}

    @router.get("")
    def listing() -> list[Course]:
        return [Course(id=1, name="Álgebra")]

    @router.post("", status_code=status.HTTP_201_CREATED)
    def create(course: Course) -> Course:
        return course

    @router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete(course_id: int) -> None:
        return None

    @router.get("/{course_id}/syllabus", response_class=PlainTextResponse)
    def syllabus(course_id: int) -> str:
        return "Unidad 1"

    @router.get("/{course_id}/raw")
    def raw(course_id: int) -> Response:
        return Response(content="tal cual", media_type="text/plain")

    @router.get("/{course_id}/built")
    def built(course_id: int) -> dict:
        return ok({"id": course_id}, 200)  # type: ignore[return-value]

    app.include_router(router)

    @app.get("/health")
    @skip_envelope
    def health() -> dict:
        return {"status": "ok"}

    return TestClient(app)


def test_a_route_declared_in_the_app_answers_with_the_envelope():
    assert _client().get("/plain").json() == {
        "success": True,
        "status": 200,
        "data": {"a": 1},
        "errors": [],
    }


def test_the_envelope_keeps_only_what_the_model_declares():
    body = _client().get("/courses/7").json()

    assert body["data"] == {"id": 7, "name": "Álgebra"}


def test_a_router_included_in_the_app_is_wrapped_once():
    body = _client().get("/courses").json()

    assert body["data"] == [{"id": 1, "name": "Álgebra"}]
    assert "success" not in body["data"][0]


def test_the_status_of_the_envelope_is_the_one_the_route_declares():
    r = _client().post("/courses", json={"id": 2, "name": "Cálculo"})

    assert r.status_code == 201
    assert r.json()["status"] == 201


def test_what_has_no_body_or_is_not_json_goes_out_as_it_is():
    client = _client()

    assert client.delete("/courses/1").status_code == 204
    assert client.get("/courses/1/syllabus").text == "Unidad 1"
    assert client.get("/courses/1/raw").text == "tal cual"
    assert client.get("/health").json() == {"status": "ok"}


def test_a_body_that_is_already_an_envelope_is_not_wrapped_again():
    body = _client().get("/courses/3/built").json()

    assert body["data"] == {"id": 3}


def test_the_documentation_shows_the_envelope_around_the_model():
    schema = _client().get("/openapi.json").json()

    answer = schema["paths"]["/courses/{course_id}"]["get"]["responses"]["200"]
    ref = answer["content"]["application/json"]["schema"]["$ref"]
    envelope = schema["components"]["schemas"][ref.rsplit("/", 1)[1]]
    assert set(envelope["properties"]) >= {"success", "status", "data", "errors"}
