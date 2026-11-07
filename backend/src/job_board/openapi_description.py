"""The API's OpenAPI description, committed as the contract between the backend and the web app.

Invariant: ``backend/openapi.json`` is exactly what ``render()`` returns for the
current routes and models. A test compares the two, and the web app's request
and response types are generated from the file, so a change to a route reaches
the front end only through a rewritten file.

    uv run python -m job_board.openapi_description    # from backend/
"""

import json
from pathlib import Path

from job_board.app import create_app
from job_board.settings import Settings

# The source checkout's backend/ folder: the file is written beside pyproject.toml.
DESCRIPTION_PATH = Path(__file__).resolve().parents[2] / "openapi.json"
REWRITE_COMMAND = "uv run python -m job_board.openapi_description"


def render() -> str:
    """The description as the committed file holds it: indented JSON in FastAPI's key order.

    The settings are built without validation or the environment, so the
    description needs no database and no real setting. Required settings are
    absent, and reading one while building the app fails here at once.
    Defaulted settings take their defaults, so the description is the app as
    built with defaults: no route may be registered on a setting's value.
    """
    app = create_app(Settings.model_construct())
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    DESCRIPTION_PATH.write_bytes(render().encode())  # bytes, so no platform rewrites the newlines


if __name__ == "__main__":
    main()
