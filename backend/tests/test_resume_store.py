import socket
from collections.abc import Iterator

import pytest
from botocore.config import Config
from pydantic import SecretStr

from job_board.resumes import store
from job_board.resumes.store import StoreDidNotAnswer, open_store
from job_board.settings import StorageSettings


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    """A loopback socket that takes connections into its backlog and never answers."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(16)
        yield server


def connections_made(server: socket.socket) -> int:
    server.setblocking(False)
    made = 0
    while True:
        try:
            connection, _ = server.accept()
        except BlockingIOError:
            return made
        connection.close()
        made += 1


async def test_gives_up_on_a_store_that_never_answers_after_two_tries(
    listener: socket.socket, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The client's own retry setting, with its read timeout cut so the test
    # waits a fraction of a second for each try rather than twenty.
    monkeypatch.setattr(store, "CLIENT_CONFIG", store.CLIENT_CONFIG.merge(Config(read_timeout=0.2)))
    port = listener.getsockname()[1]
    resume_store = open_store(
        StorageSettings(
            endpoint_url=f"http://127.0.0.1:{port}",
            region="auto",
            bucket="resumes",
            access_key_id=SecretStr("an-access-key-id"),
            secret_access_key=SecretStr("a-secret-access-key"),
        )
    )
    assert resume_store is not None

    with pytest.raises(StoreDidNotAnswer):
        await resume_store.delete("a-key")
    resume_store.close()

    assert connections_made(listener) == 2
