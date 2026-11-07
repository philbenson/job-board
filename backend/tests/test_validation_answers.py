import json

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, field_validator

from job_board.validation_answers import answer_refused_requests

SECRET = "sk-ant-api03-secret-value-that-must-not-come-back"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    secret: str


class Friendly(BaseModel):
    word: str

    @field_validator("word")
    @classmethod
    def refuse_every_word(cls, word: str) -> str:
        raise ValueError("ce mot est refusé ✗")


def small_app() -> FastAPI:
    app = FastAPI()
    answer_refused_requests(app)

    @app.post("/strict")
    async def strict(body: Strict) -> dict[str, str]:
        return {"name": body.name}

    @app.post("/friendly")
    async def friendly(body: Friendly) -> dict[str, str]:
        return {"word": body.word}

    return app


async def post(path: str, *, content: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=small_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path, content=content, headers={"Content-Type": "application/json"}
        )


async def test_a_missing_field_quotes_nothing_of_the_body() -> None:
    body = json.dumps({"secret": SECRET}).encode()
    response = await post("/strict", content=body)

    assert response.status_code == 422
    (problem,) = response.json()["detail"]
    assert set(problem) == {"type", "loc", "msg"}
    assert problem["loc"] == ["body", "name"]
    assert SECRET not in response.text


async def test_an_extra_key_named_half_a_surrogate_pair_is_still_refused_as_422() -> None:
    # Pydantic cannot read a key that is not text and refuses the whole body, so
    # FastAPI's own answer, which quotes that body, could not be written at all.
    body = b'{"name":"x","secret":"y","\\ud800":1}'
    response = await post("/strict", content=body)

    assert response.status_code == 422
    (problem,) = response.json()["detail"]
    assert set(problem) == {"type", "loc", "msg"}
    assert problem["loc"] == ["body"]


async def test_the_answer_is_json_and_carries_any_message_intact() -> None:
    response = await post("/friendly", content=b'{"word":"bonjour"}')

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert response.content.isascii()
    (problem,) = response.json()["detail"]
    assert problem["msg"] == "Value error, ce mot est refusé ✗"
