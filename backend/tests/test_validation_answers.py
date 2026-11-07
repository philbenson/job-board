import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from job_board.validation_answers import answer_refused_requests


class Named(BaseModel):
    name: str
    count: int


def app_answering_refusals() -> FastAPI:
    app = FastAPI()
    answer_refused_requests(app)

    @app.post("/named")
    async def take(body: Named) -> Named:
        return body

    return app


async def send(body: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=app_answering_refusals())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/named", content=body, headers={"Content-Type": "application/json"}
        )


async def test_echoes_half_a_surrogate_pair_in_a_refusal_instead_of_failing() -> None:
    # JSON can spell half of a surrogate pair, which UTF-8 cannot carry back.
    response = await send(b'{"name": "Ada", "count": "\\ud800"}')

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "count"]
    assert error["input"] == "\ud800"


async def test_answers_a_refusal_as_fastapi_does() -> None:
    response = await send('{"name": "Zoë", "count": "many"}'.encode())

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "detail": [
            {
                "type": "int_parsing",
                "loc": ["body", "count"],
                "msg": "Input should be a valid integer, unable to parse string as an integer",
                "input": "many",
            }
        ]
    }
