import pytest
from pydantic import ValidationError

from job_board.settings import EXPECTED_FORM, Settings, sqlalchemy_url

PLAIN = "postgresql://reader:hunter2@db.example.com:5432/jobs"
DRIVER = "postgresql+psycopg://reader:hunter2@db.example.com:5432/jobs"


def test_reads_the_database_url_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", PLAIN)
    settings = Settings(_env_file=None)
    assert settings.database_url.get_secret_value() == DRIVER


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+psycopg", "PostgreSQL"])
def test_hands_sqlalchemy_the_psycopg_driver(scheme: str) -> None:
    assert sqlalchemy_url(f"{scheme}://reader:hunter2@db.example.com:5432/jobs") == DRIVER


@pytest.mark.parametrize(
    "url",
    [
        "mysql://reader:hunter2@db.example.com:5432/jobs",
        "postgresql+asyncpg://reader:hunter2@db.example.com:5432/jobs",
        "reader:hunter2@db.example.com:5432/jobs",
        "postgresql://reader:hunter2@db.example.com:fivefour/jobs",
    ],
)
def test_refuses_any_other_form_without_repeating_it(url: str) -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(database_url=url, _env_file=None)
    message = str(raised.value)
    assert "DATABASE_URL" in message
    assert EXPECTED_FORM in message
    for leak in ("hunter2", "db.example.com", "reader", "fivefour", "mysql", "asyncpg"):
        assert leak not in message


def test_never_shows_the_database_url() -> None:
    settings = Settings(database_url=PLAIN, _env_file=None)
    for shown in (repr(settings), str(settings), settings.model_dump_json()):
        assert "hunter2" not in shown
        assert "db.example.com" not in shown
