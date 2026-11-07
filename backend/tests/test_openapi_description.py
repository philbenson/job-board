import pytest

from job_board.openapi_description import DESCRIPTION_PATH, REWRITE_COMMAND, render


def test_the_committed_description_matches_the_app() -> None:
    committed = DESCRIPTION_PATH.read_bytes() if DESCRIPTION_PATH.exists() else None
    if committed != render().encode():
        pytest.fail(
            "backend/openapi.json does not match the app's routes and models: "
            f"run `{REWRITE_COMMAND}` from backend/ and commit the result",
            pytrace=False,
        )
