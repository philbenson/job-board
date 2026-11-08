import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from held_reader import FILLER, HeldReader
from local_s3 import LocalBucket
from pdf_files import pdf, resume_lines
from resume_service import (
    A_PDF,
    A_PDF_TEXT,
    ACCESS_KEY_ID,
    SECRET_ACCESS_KEY,
    Service,
    Someone,
    pdf_headers,
    run,
    service_for,
    storage_settings,
)
from settings_for_tests import make_settings
from starlette.types import Message

from job_board.app import create_app
from job_board.logging_setup import LOGGER_NAME

LARGEST = 5 * 1024 * 1024
CHUNK = 64 * 1024

NOT_SET_UP = {"detail": "Resume storage is not set up"}
DID_NOT_ANSWER = {"detail": "Resume storage did not answer; try again later"}
SEND_A_PDF = {"detail": "Send the resume as a PDF"}
NOT_A_PDF = {"detail": "That file is not a PDF"}
SEND_THE_LENGTH = {"detail": "Send the file's length"}
TOO_LARGE = {"detail": "A resume can be at most 5 MB"}
LONGER_THAN_DECLARED = {"detail": "The file is longer than its declared length"}
ENDED_EARLY = {"detail": "The file ended before its declared length"}
READING_BUSY = {"detail": "Resume reading is busy; try again in a minute"}


@pytest.fixture
def someone(migrated_database_url: str) -> Iterator[Someone]:
    person = Someone(migrated_database_url)
    yield person
    person.remove()


@pytest.fixture
def someone_else(migrated_database_url: str) -> Iterator[Someone]:
    person = Someone(migrated_database_url)
    yield person
    person.remove()


@pytest.fixture
async def service(
    migrated_database_url: str, local_s3: str, s3_bucket: LocalBucket
) -> AsyncIterator[Service]:
    settings = storage_settings(local_s3, s3_bucket.name)
    async with service_for(migrated_database_url, **settings) as running:
        yield running


@dataclass
class CountedBody:
    """A request body sent a chunk at a time, counting the chunks the service asked for.

    Given the service, it also notes, as each chunk is asked for, whether the
    request's session is in a transaction and how many pooled connections are
    checked out.
    """

    chunks: list[bytes]
    asked: int = 0
    service: Service | None = None
    seen: list[tuple[bool, int]] = field(default_factory=list)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.asked += 1
            if self.service is not None:
                session = self.service.sessions[-1]
                checked_out = self.service.app.state.engine.pool.checkedout()
                self.seen.append((session.in_transaction(), checked_out))
            yield chunk


def in_chunks(body: bytes) -> list[bytes]:
    return [body[start : start + CHUNK] for start in range(0, len(body), CHUNK)]


async def test_not_set_up_warns_once_at_start_and_every_route_answers_503(
    migrated_database_url: str, someone: Someone, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        async with service_for(migrated_database_url) as service:
            started = [record.getMessage() for record in caplog.records]
            answers = [
                await service.client.get("/resume", headers=someone.headers),
                await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF),
                await service.client.delete("/resume", headers=someone.headers),
            ]

    assert started == ["resume storage is not set up: the resume routes answer 503"]
    assert [(answer.status_code, answer.json()) for answer in answers] == [(503, NOT_SET_UP)] * 3
    assert len(caplog.records) == 1


async def test_reads_no_resume_before_the_first_upload(service: Service, someone: Someone) -> None:
    response = await service.client.get("/resume", headers=someone.headers)
    assert response.status_code == 200
    assert response.json() == {"resume": None}


async def test_an_upload_stores_the_file_and_answers_what_reading_answers(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    uploaded = await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)
    read = await service.client.get("/resume", headers=someone.headers)

    assert uploaded.status_code == 200
    assert uploaded.json() == read.json()
    (row,) = someone.rows()
    saved = uploaded.json()["resume"]
    assert saved["size_bytes"] == len(A_PDF)
    assert datetime.fromisoformat(saved["uploaded_at"]) == row.uploaded_at
    assert (row.object_key, row.size_bytes) == (someone.key(), len(A_PDF))
    assert s3_bucket.stored_keys() == [someone.key()]
    assert s3_bucket.read(someone.key()) == (A_PDF, "application/pdf")


async def test_a_second_upload_replaces_the_file_and_the_row(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    second = b"%PDF-2.0\n" + secrets.token_bytes(LARGEST - 9)
    await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)
    (first_row,) = someone.rows()

    replaced = await service.client.put("/resume", headers=pdf_headers(someone), content=second)

    assert replaced.status_code == 200
    (row,) = someone.rows()
    assert row.size_bytes == LARGEST
    assert row.uploaded_at >= first_row.uploaded_at
    assert s3_bucket.stored_keys() == [someone.key()]
    assert s3_bucket.read(someone.key())[0] == second


async def test_an_upload_keeps_the_text_read_from_the_file_unchecked(
    service: Service, someone: Someone
) -> None:
    uploaded = await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)

    assert uploaded.status_code == 200
    assert uploaded.json().keys() == {"resume"}
    assert uploaded.json()["resume"].keys() == {"size_bytes", "uploaded_at"}
    assert tuple(someone.text_row()) == ("found", A_PDF_TEXT, None)


async def test_a_second_upload_reads_its_own_text_and_clears_the_check(
    service: Service, someone: Someone
) -> None:
    await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)
    someone.check_text()
    assert someone.text_row().text_checked_at is not None
    unreadable = b"%PDF-1.7\n" + secrets.token_bytes(2048) + b"\n%%EOF\n"

    replaced = await service.client.put("/resume", headers=pdf_headers(someone), content=unreadable)

    assert replaced.status_code == 200
    assert tuple(someone.text_row()) == ("failed", None, None)


async def test_an_upload_refused_as_busy_changes_neither_the_store_nor_the_row(
    service: Service, someone: Someone, s3_bucket: LocalBucket, caplog: pytest.LogCaptureFixture
) -> None:
    reader = HeldReader()
    service.app.state.resume_text_reader = reader
    reader.let_go.set()
    await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)
    before = (someone.rows(), tuple(someone.text_row()), s3_bucket.read(someone.key()))
    reader.let_go.clear()
    being_read = pdf(resume_lines()[:4])
    first = asyncio.create_task(
        service.client.put("/resume", headers=pdf_headers(someone), content=being_read)
    )
    await reader.reading_begins(2)

    with caplog.at_level(logging.WARNING):
        refused = await service.client.put(
            "/resume", headers=pdf_headers(someone), content=pdf(resume_lines()[4:])
        )

    assert (refused.status_code, refused.json()) == (503, READING_BUSY)
    assert (someone.rows(), tuple(someone.text_row()), s3_bucket.read(someone.key())) == before
    ours = [record.getMessage() for record in caplog.records if record.name.startswith("job_board")]
    assert ours == [
        "resume text reading refused as busy: that person's upload is already being read or waiting"
    ]
    reader.let_go.set()
    assert (await first).status_code == 200
    assert s3_bucket.read(someone.key()) == (being_read, "application/pdf")
    assert tuple(someone.text_row()) == ("found", FILLER, None)


async def test_takes_the_media_type_whatever_its_case_and_parameters(
    service: Service, someone: Someone
) -> None:
    headers = pdf_headers(someone, **{"Content-Type": "Application/PDF; name=cv"})
    response = await service.client.put("/resume", headers=headers, content=A_PDF)
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("content_type", "body", "declared", "answer"),
    [
        pytest.param("text/plain", A_PDF, None, (415, SEND_A_PDF), id="another-media-type"),
        pytest.param(None, A_PDF, None, (415, SEND_A_PDF), id="no-media-type"),
        pytest.param("application/pdfx", A_PDF, None, (415, SEND_A_PDF), id="a-longer-type"),
        pytest.param("application/pdf", A_PDF, "many", (411, SEND_THE_LENGTH), id="not-a-number"),
        pytest.param("application/pdf", A_PDF, "-1", (411, SEND_THE_LENGTH), id="negative"),
        pytest.param("application/pdf", b"", "0", (415, NOT_A_PDF), id="empty"),
        pytest.param("application/pdf", b"%PD", None, (415, NOT_A_PDF), id="under-five-bytes"),
        pytest.param("application/pdf", b"GIF89a" + A_PDF, None, (415, NOT_A_PDF), id="a-gif"),
    ],
)
async def test_refuses_what_is_not_a_pdf_storing_nothing(
    service: Service,
    someone: Someone,
    s3_bucket: LocalBucket,
    content_type: str | None,
    body: bytes,
    declared: str | None,
    answer: tuple[int, dict[str, str]],
) -> None:
    headers = dict(someone.headers)
    if content_type is not None:
        headers["Content-Type"] = content_type
    if declared is not None:
        headers["Content-Length"] = declared

    response = await service.client.put("/resume", headers=headers, content=body)

    assert (response.status_code, response.json()) == answer
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_refuses_a_body_without_a_declared_length(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    body = CountedBody(in_chunks(A_PDF))  # sent chunked, with no Content-Length

    response = await service.client.put("/resume", headers=pdf_headers(someone), content=body)

    assert (response.status_code, response.json()) == (411, SEND_THE_LENGTH)
    assert body.asked == 0
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_refuses_a_declared_length_over_5_mb_unread(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    body = CountedBody(in_chunks(b"%PDF-" + bytes(LARGEST)))
    headers = pdf_headers(someone, **{"Content-Length": str(LARGEST + 5)})

    response = await service.client.put("/resume", headers=headers, content=body)

    assert (response.status_code, response.json()) == (413, TOO_LARGE)
    assert body.asked == 0
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_stops_reading_a_body_that_runs_past_its_declared_length(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    body = CountedBody(in_chunks(b"%PDF-" + bytes(2 * LARGEST)))
    headers = pdf_headers(someone, **{"Content-Length": str(LARGEST)})

    response = await service.client.put("/resume", headers=headers, content=body)

    assert (response.status_code, response.json()) == (413, LONGER_THAN_DECLARED)
    assert body.asked == LARGEST // CHUNK + 1  # the chunk that ran past, and none after
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_stops_reading_at_the_first_bytes_that_are_not_a_pdf(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    body = CountedBody([b"GIF", b"89a", *in_chunks(bytes(LARGEST - 6))])
    headers = pdf_headers(someone, **{"Content-Length": str(LARGEST)})

    response = await service.client.put("/resume", headers=headers, content=body)

    assert (response.status_code, response.json()) == (415, NOT_A_PDF)
    assert body.asked == 2  # five bytes are in after the second chunk
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_refuses_a_body_that_ends_before_its_declared_length_storing_nothing(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    # The body ends with more_body False, as a server that does not send a
    # disconnect would end it.
    body = CountedBody([A_PDF[:100]])
    headers = pdf_headers(someone, **{"Content-Length": "200"})

    response = await service.client.put("/resume", headers=headers, content=body)

    assert (response.status_code, response.json()) == (400, ENDED_EARLY)
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_an_unsigned_upload_is_refused_before_a_byte_of_it_is_read(
    service: Service, s3_bucket: LocalBucket
) -> None:
    body = CountedBody(in_chunks(b"%PDF-" + bytes(1024 * 1024 - 5)))
    headers = {"Content-Type": "application/pdf", "Content-Length": str(1024 * 1024)}

    response = await service.client.put("/resume", headers=headers, content=body)

    assert response.status_code == 401
    assert body.asked == 0
    assert s3_bucket.stored_keys() == []


async def test_a_client_that_goes_away_mid_upload_leaves_nothing_stored(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    await service.client.get("/resume", headers=someone.headers)  # adds the person
    arriving: list[Message] = [
        {"type": "http.request", "body": A_PDF[:100], "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return arriving.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    headers = pdf_headers(someone, **{"Content-Length": str(len(A_PDF))})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": "/resume",
        "raw_path": b"/resume",
        "root_path": "",
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
        "state": {},
    }
    await service.app(scope, receive, send)

    assert sent[0]["status"] == 400
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


@dataclass
class WatchedReader:
    """Stands in front of the service's text reader, noting the request's database state."""

    reader: Any
    store: WatchedStore

    async def read(self, file: bytes | bytearray, person: Any) -> Any:
        self.store.look("read")
        return await self.reader.read(file, person)


@dataclass
class WatchedStore:
    """Stands in front of the service's store, noting the request's database state at each call."""

    store: Any
    service: Service
    seen: list[tuple[str, bool, int]] = field(default_factory=list)

    def look(self, operation: str) -> None:
        session = self.service.sessions[-1]
        checked_out = self.service.app.state.engine.pool.checkedout()
        self.seen.append((operation, session.in_transaction(), checked_out))

    async def put(self, key: str, body: bytes | bytearray) -> None:
        self.look("put")
        await self.store.put(key, body)

    async def delete(self, key: str) -> None:
        self.look("delete")
        await self.store.delete(key)


async def test_holds_no_database_transaction_or_connection_while_the_text_or_store_answers(
    service: Service, someone: Someone
) -> None:
    watched = WatchedStore(service.app.state.resume_store, service)
    service.app.state.resume_store = watched
    reader = WatchedReader(service.app.state.resume_text_reader, watched)
    service.app.state.resume_text_reader = reader

    uploaded = await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)
    removed = await service.client.delete("/resume", headers=someone.headers)

    assert (uploaded.status_code, removed.status_code) == (200, 204)
    # The text is read once the file is in, and before the store keeps it.
    assert watched.seen == [("read", False, 0), ("put", False, 0), ("delete", False, 0)]


async def test_holds_no_database_transaction_or_connection_while_the_file_arrives(
    service: Service, someone: Someone
) -> None:
    file = b"%PDF-" + bytes(3 * CHUNK - 5)
    body = CountedBody(in_chunks(file), service=service)
    headers = pdf_headers(someone, **{"Content-Length": str(len(file))})

    response = await service.client.put("/resume", headers=headers, content=body)

    assert response.status_code == 200
    assert body.seen == [(False, 0)] * 3


async def test_a_store_that_does_not_answer_changes_nothing_and_is_logged_without_secrets(
    migrated_database_url: str,
    someone: Someone,
    closed_port: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    endpoint = f"http://127.0.0.1:{closed_port}"
    # Building the service sets its own loggers to info, after which the store opens
    # with the keys in hand: the resume modules' logger is lowered first, which
    # the build leaves alone, and the whole service's once it is up.
    caplog.set_level(logging.DEBUG, logger=f"{LOGGER_NAME}.resumes")
    with caplog.at_level(logging.DEBUG):
        async with service_for(
            migrated_database_url, **storage_settings(endpoint, "resumes")
        ) as service:
            caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
            await service.client.get("/resume", headers=someone.headers)  # adds the person
            run(
                migrated_database_url,
                "INSERT INTO resumes (person_id, object_key, size_bytes) VALUES (:person, :key, 9)",
                person=someone.person_id(),
                key=someone.key(),
            )
            before = someone.rows()
            uploaded = await service.client.put(
                "/resume", headers=pdf_headers(someone), content=A_PDF
            )
            removed = await service.client.delete("/resume", headers=someone.headers)

    assert (uploaded.status_code, uploaded.json()) == (503, DID_NOT_ANSWER)
    assert (removed.status_code, removed.json()) == (503, DID_NOT_ANSWER)
    assert someone.rows() == before
    ours = [record.getMessage() for record in caplog.records if record.name.startswith("job_board")]
    assert ours == [
        "resume storage did not answer put_object: EndpointConnectionError",
        "resume storage did not answer delete_object: EndpointConnectionError",
    ]
    assert SECRET_ACCESS_KEY not in caplog.text
    # The key id is in the signed request's header, which botocore itself logs
    # at debug; the service never writes botocore's debug lines.
    for record in caplog.records:
        if record.levelno >= logging.INFO or record.name.startswith("job_board"):
            assert ACCESS_KEY_ID not in record.getMessage()


async def test_a_refusal_from_the_store_is_logged_with_its_error_code(
    migrated_database_url: str,
    local_s3: str,
    someone: Someone,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing_bucket = f"absent-{secrets.token_hex(6)}"
    with caplog.at_level(logging.WARNING, logger="job_board"):
        async with service_for(
            migrated_database_url, **storage_settings(local_s3, missing_bucket)
        ) as service:
            response = await service.client.put(
                "/resume", headers=pdf_headers(someone), content=A_PDF
            )

    assert (response.status_code, response.json()) == (503, DID_NOT_ANSWER)
    assert someone.rows() == []
    # The local server logs its own way in this process too; only the service's lines count.
    ours = [record.getMessage() for record in caplog.records if record.name.startswith("job_board")]
    assert ours == ["resume storage did not answer put_object: ClientError NoSuchBucket"]


async def test_removes_the_file_and_the_row(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)

    removed = await service.client.delete("/resume", headers=someone.headers)
    read = await service.client.get("/resume", headers=someone.headers)

    assert removed.status_code == 204
    assert removed.content == b""
    assert read.json() == {"resume": None}
    assert someone.rows() == []
    assert s3_bucket.stored_keys() == []


async def test_removing_when_there_is_nothing_answers_204(
    service: Service, someone: Someone
) -> None:
    removed = await service.client.delete("/resume", headers=someone.headers)
    assert removed.status_code == 204


async def test_removing_clears_a_file_left_without_its_row(
    service: Service, someone: Someone, s3_bucket: LocalBucket
) -> None:
    await service.client.get("/resume", headers=someone.headers)  # adds the person
    s3_bucket.put(someone.key(), A_PDF)

    removed = await service.client.delete("/resume", headers=someone.headers)

    assert removed.status_code == 204
    assert s3_bucket.stored_keys() == []


async def test_a_person_can_neither_read_nor_remove_another_persons_resume(
    service: Service, someone: Someone, someone_else: Someone, s3_bucket: LocalBucket
) -> None:
    await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)

    read = await service.client.get("/resume", headers=someone_else.headers)
    removed = await service.client.delete("/resume", headers=someone_else.headers)

    assert read.json() == {"resume": None}
    assert removed.status_code == 204
    assert len(someone.rows()) == 1
    assert s3_bucket.stored_keys() == [someone.key()]


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_every_route_needs_a_signed_in_person(method: str, service: Service) -> None:
    response = await service.client.request(
        method, "/resume", headers={"Content-Type": "application/pdf"}, content=A_PDF
    )
    assert response.status_code == 401


async def test_reaches_the_store_named_by_its_settings_whatever_the_aws_environment_says(
    migrated_database_url: str,
    local_s3: str,
    s3_bucket: LocalBucket,
    someone: Someone,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    closed_port: int,
) -> None:
    config_file = tmp_path / "aws-config"
    config_file.write_text(
        "[default]\nregion = nowhere-1\nendpoint_url = https://elsewhere.example.com\n"
        "s3 =\n  use_accelerate_endpoint = true\n"
    )
    for name, value in {
        "AWS_ENDPOINT_URL": "https://elsewhere.example.com",
        "AWS_ENDPOINT_URL_S3": "https://elsewhere.example.com",
        "AWS_ACCESS_KEY_ID": "elsewhere-access-key-id",
        "AWS_SECRET_ACCESS_KEY": "elsewhere-secret-access-key",
        "AWS_SESSION_TOKEN": "elsewhere-session-token",
        "AWS_DEFAULT_REGION": "nowhere-1",
        "AWS_PROFILE": "no-such-profile",
        "AWS_CONFIG_FILE": str(config_file),
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "no-such-credentials"),
        "AWS_USE_DUALSTACK_ENDPOINT": "true",
        "AWS_USE_FIPS_ENDPOINT": "true",
        "AWS_CA_BUNDLE": str(tmp_path / "no-such-bundle.pem"),
        "HTTP_PROXY": f"http://127.0.0.1:{closed_port}",
        "HTTPS_PROXY": f"http://127.0.0.1:{closed_port}",
        # Empty, so that no bypass for this machine's own address hides a
        # client that reads the proxy variables.
        "NO_PROXY": "",
    }.items():
        monkeypatch.setenv(name, value)
    # The lower case spellings, which Python reads before these, are the shell's.
    for name in ("http_proxy", "https_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)

    settings = storage_settings(local_s3, s3_bucket.name)
    async with service_for(migrated_database_url, **settings) as service:
        response = await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)

    assert response.status_code == 200
    assert s3_bucket.read(someone.key()) == (A_PDF, "application/pdf")


def test_the_description_declares_each_answer_and_the_file_as_the_body() -> None:
    description = create_app(make_settings()).openapi()
    route = description["paths"]["/resume"]
    schemas = description["components"]["schemas"]

    assert set(route) == {"get", "put", "delete"}
    assert set(route["get"]["responses"]) == {"200", "401", "503"}
    assert set(route["put"]["responses"]) == {"200", "400", "401", "411", "413", "415", "503"}
    assert route["put"]["responses"]["503"]["description"] == (
        "Resume storage is not set up, or did not answer, or reading is busy"
    )
    assert set(route["delete"]["responses"]) == {"204", "401", "503"}
    assert route["put"]["requestBody"] == {
        "required": True,
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
    }
    for status in ("400", "411", "413", "415", "503"):
        refusal = route["put"]["responses"][status]["content"]["application/json"]["schema"]
        assert refusal == {"$ref": "#/components/schemas/Refused"}
    assert schemas["Resume"]["required"] == ["resume"]
    assert schemas["SavedResume"]["required"] == ["size_bytes", "uploaded_at"]
