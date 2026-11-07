import httpx
import pytest
from settings_for_tests import make_settings

from job_board.app import create_app


async def test_the_built_app_writes_a_refused_sign_in_to_stderr(
    closed_port: int, capfd: pytest.CaptureFixture[str]
) -> None:
    # As the service runs: no test sets a log level, so only what create_app
    # configures decides whether the line is written.
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    app = create_app(make_settings(database_url=unreachable))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/me")

    assert response.status_code == 401
    assert "sign-in refused: missing" in capfd.readouterr().err


async def test_building_the_app_twice_writes_each_line_once(
    closed_port: int, capfd: pytest.CaptureFixture[str]
) -> None:
    unreachable = f"postgresql://job_board:s3cret@127.0.0.1:{closed_port}/job_board"
    create_app(make_settings(database_url=unreachable))
    app = create_app(make_settings(database_url=unreachable))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/me")

    assert capfd.readouterr().err.count("sign-in refused: missing") == 1
