from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from settings_for_tests import make_settings

from job_board.app import create_app
from job_board.body_limit import LARGEST_BODY_BYTES, BodyLimit

TOO_LARGE = {"detail": "The request body is too large"}


def counting_app() -> tuple[FastAPI, list[int]]:
    """An app whose one route reads the body and keeps its length."""
    app = FastAPI()
    app.add_middleware(BodyLimit)
    received: list[int] = []

    @app.post("/count")
    async def count(request: Request) -> dict[str, int]:
        received.append(len(await request.body()))
        return {"length": received[-1]}

    return app, received


async def post(app: FastAPI, **sent: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/count", **sent)  # type: ignore[arg-type]


async def test_refuses_a_declared_length_over_the_cap_without_running_the_route() -> None:
    app, received = counting_app()

    response = await post(app, content=b"x" * (LARGEST_BODY_BYTES + 1))

    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert response.headers["content-type"] == "application/json"
    assert received == []


async def test_refuses_a_streamed_body_once_it_passes_the_cap() -> None:
    app, received = counting_app()

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * (LARGEST_BODY_BYTES // 4)

    response = await post(app, content=chunks())

    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert received == []


async def test_takes_a_body_of_exactly_the_cap() -> None:
    app, received = counting_app()

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"x" * (LARGEST_BODY_BYTES // 4)

    declared = await post(app, content=b"x" * LARGEST_BODY_BYTES)
    streamed = await post(app, content=chunks())

    assert declared.status_code == 200
    assert streamed.status_code == 200
    assert received == [LARGEST_BODY_BYTES, LARGEST_BODY_BYTES]


async def test_the_service_refuses_an_oversized_body_before_asking_who_sent_it() -> None:
    app = create_app(make_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/model-key",
            content=b"x" * (LARGEST_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413  # not the 401 an unsigned request gets
    assert response.json() == TOO_LARGE


def resume_routes_app() -> tuple[FastAPI, list[tuple[str, str, int]]]:
    """An app with resume-like routes that each read the body and keep its length."""
    app = FastAPI()
    app.add_middleware(BodyLimit)
    received: list[tuple[str, str, int]] = []

    async def count(request: Request) -> None:
        received.append((request.method, request.url.path, len(await request.body())))

    app.add_api_route("/resume", count, methods=["PUT", "POST"])
    app.add_api_route("/resume/", count, methods=["PUT"])
    return app, received


ONE_MEBIBYTE = b"x" * (1024 * 1024)


async def test_passes_the_resume_upload_through_unread_whatever_its_size() -> None:
    app, received = resume_routes_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/resume", content=ONE_MEBIBYTE)

    assert response.status_code == 200
    assert received == [("PUT", "/resume", len(ONE_MEBIBYTE))]


async def test_caps_every_other_method_and_path_beside_the_resume_upload() -> None:
    app, received = resume_routes_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        posted = await client.post("/resume", content=ONE_MEBIBYTE)
        slashed = await client.put("/resume/", content=ONE_MEBIBYTE)

    assert (posted.status_code, posted.json()) == (413, TOO_LARGE)
    assert (slashed.status_code, slashed.json()) == (413, TOO_LARGE)
    assert received == []


async def test_passes_the_resume_upload_through_unread_under_a_root_path() -> None:
    # Served under a root path, as uvicorn's --root-path serves it, the scope's
    # path carries the root path in front of the route's own.
    app, received = resume_routes_app()
    transport = httpx.ASGITransport(app=app, root_path="/jobs")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        uploaded = await client.put("/jobs/resume", content=ONE_MEBIBYTE)
        posted = await client.post("/jobs/resume", content=ONE_MEBIBYTE)

    assert uploaded.status_code == 200
    assert (posted.status_code, posted.json()) == (413, TOO_LARGE)
    assert received == [("PUT", "/jobs/resume", len(ONE_MEBIBYTE))]
