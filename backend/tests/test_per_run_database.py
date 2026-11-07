import pytest
from per_run_database import START_COMMAND, per_run_database, server_url
from sqlalchemy import create_engine, make_url, text


def test_creates_a_fresh_database_and_drops_it() -> None:
    server = server_url()
    with per_run_database(server) as url:
        name = make_url(url).database
        assert name is not None
        assert name.startswith("job_board_test_")
        assert name != server.database
        engine = create_engine(url)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar_one() == name
        engine.dispose()

    admin = create_engine(server)
    with admin.connect() as connection:
        exists = connection.execute(
            text("SELECT count(*) FROM pg_database WHERE datname = :name"), {"name": name}
        ).scalar_one()
    admin.dispose()
    assert exists == 0


def test_an_unreachable_server_fails_the_run_with_the_start_command(closed_port: int) -> None:
    server = make_url(f"postgresql+psycopg://job_board:job_board@127.0.0.1:{closed_port}/job_board")
    with pytest.raises(pytest.fail.Exception, match=START_COMMAND), per_run_database(server):
        pass
