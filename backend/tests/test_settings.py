import pytest

from job_board.settings import Settings

URL = "postgresql+psycopg://reader:hunter2@db.example.com:5432/jobs"


def test_reads_the_database_url_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    settings = Settings(_env_file=None)
    assert settings.database_url.get_secret_value() == URL


def test_never_shows_the_database_url() -> None:
    settings = Settings(database_url=URL, _env_file=None)
    for shown in (repr(settings), str(settings), settings.model_dump_json()):
        assert "hunter2" not in shown
        assert "db.example.com" not in shown
