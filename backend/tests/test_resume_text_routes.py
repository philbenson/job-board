import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from local_s3 import LocalBucket
from resume_service import (
    A_PDF,
    A_PDF_TEXT,
    Service,
    Someone,
    pdf_headers,
    run,
    service_for,
    storage_settings,
)
from settings_for_tests import make_settings

from job_board.app import create_app

NO_RESUME = {"detail": "No resume uploaded"}
REPLACED = {"detail": "Your resume was replaced since this text was read"}
NOT_SET_UP = {"detail": "Resume storage is not set up"}
CHECKED = "Avery Example\nStaff Engineer, Example Widgets\n\nLed the move to small services."


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


async def uploaded(service: Service, person: Someone, file: bytes = A_PDF) -> dict[str, Any]:
    """Uploads ``file`` as the person's resume and answers what reading its text gives."""
    response = await service.client.put("/resume", headers=pdf_headers(person), content=file)
    assert response.status_code == 200
    read = await service.client.get("/resume/text", headers=person.headers)
    assert read.status_code == 200
    answer: dict[str, Any] = read.json()
    return answer


async def save(service: Service, person: Someone, body: object) -> Any:
    # Escaped to ASCII, so a half of a surrogate pair can be sent at all.
    headers = {**person.headers, "Content-Type": "application/json"}
    return await service.client.put("/resume/text", headers=headers, content=json.dumps(body))


def problems(response: Any) -> list[tuple[str, list[Any], str]]:
    return [
        (problem["type"], problem["loc"], problem["msg"]) for problem in response.json()["detail"]
    ]


async def test_reads_no_text_before_the_first_upload(service: Service, someone: Someone) -> None:
    response = await service.client.get("/resume/text", headers=someone.headers)

    assert (response.status_code, response.json()) == (404, NO_RESUME)


async def test_reads_the_text_the_upload_read_unchecked(service: Service, someone: Someone) -> None:
    put = await service.client.put("/resume", headers=pdf_headers(someone), content=A_PDF)

    read = await service.client.get("/resume/text", headers=someone.headers)

    assert read.status_code == 200
    assert read.json() == {
        "uploaded_at": put.json()["resume"]["uploaded_at"],
        "state": "found",
        "text": A_PDF_TEXT,
        "checked_at": None,
    }


async def test_a_save_keeps_the_text_cleaned_and_the_time_it_was_checked(
    service: Service, someone: Someone
) -> None:
    read = await uploaded(service, someone)

    saved = await save(
        service, someone, {"text": f"  {CHECKED}  \r\n", "uploaded_at": read["uploaded_at"]}
    )

    assert saved.status_code == 200
    answer = saved.json()
    assert answer["text"] == CHECKED
    assert (answer["uploaded_at"], answer["state"]) == (read["uploaded_at"], "found")
    assert answer["checked_at"] is not None
    again = await service.client.get("/resume/text", headers=someone.headers)
    assert again.json() == answer
    assert tuple(someone.text_row())[:2] == ("found", CHECKED)


async def test_a_save_of_text_no_reading_found_is_the_persons_word(
    service: Service, someone: Someone
) -> None:
    read = await uploaded(service, someone, b"%PDF-1.7\nnot a file at all\n%%EOF\n")
    assert (read["state"], read["text"]) == ("failed", None)

    saved = await save(service, someone, {"text": CHECKED, "uploaded_at": read["uploaded_at"]})

    assert saved.status_code == 200
    assert (saved.json()["state"], saved.json()["text"]) == ("failed", CHECKED)


async def test_a_resume_from_before_the_reading_reads_with_no_state_and_takes_a_save(
    service: Service, someone: Someone
) -> None:
    await service.client.get("/resume", headers=someone.headers)  # adds the person
    run(
        someone.database_url,
        "INSERT INTO resumes (person_id, object_key, size_bytes) VALUES (:person, :key, 9)",
        person=someone.person_id(),
        key=someone.key(),
    )

    read = await service.client.get("/resume/text", headers=someone.headers)
    saved = await save(
        service, someone, {"text": CHECKED, "uploaded_at": read.json()["uploaded_at"]}
    )

    assert (read.json()["state"], read.json()["text"]) == (None, None)
    assert saved.status_code == 200
    assert (saved.json()["state"], saved.json()["text"]) == (None, CHECKED)


async def test_an_upload_time_with_microseconds_comes_back_exactly_and_saves(
    service: Service, someone: Someone
) -> None:
    await uploaded(service, someone)
    run(
        someone.database_url,
        "UPDATE resumes SET uploaded_at = '2026-11-07 15:04:05.123456+00' WHERE person_id = :p",
        p=someone.person_id(),
    )

    read = await service.client.get("/resume/text", headers=someone.headers)
    saved = await save(
        service, someone, {"text": CHECKED, "uploaded_at": read.json()["uploaded_at"]}
    )

    assert read.json()["uploaded_at"] == "2026-11-07T15:04:05.123456Z"
    assert saved.status_code == 200


async def test_a_save_without_a_resume_is_refused(service: Service, someone: Someone) -> None:
    saved = await save(service, someone, {"text": CHECKED, "uploaded_at": "2026-11-07T15:04:05Z"})

    assert (saved.status_code, saved.json()) == (404, NO_RESUME)


async def test_a_save_for_a_file_since_replaced_is_refused_and_changes_nothing(
    service: Service, someone: Someone
) -> None:
    first = await uploaded(service, someone)
    second = await uploaded(service, someone)
    assert first["uploaded_at"] != second["uploaded_at"]

    saved = await save(service, someone, {"text": CHECKED, "uploaded_at": first["uploaded_at"]})

    assert (saved.status_code, saved.json()) == (409, REPLACED)
    assert tuple(someone.text_row()) == ("found", A_PDF_TEXT, None)


async def test_another_persons_upload_time_saves_nothing_for_either(
    service: Service, someone: Someone, someone_else: Someone
) -> None:
    await uploaded(service, someone)
    theirs = await uploaded(service, someone_else)

    saved = await save(service, someone, {"text": CHECKED, "uploaded_at": theirs["uploaded_at"]})

    assert (saved.status_code, saved.json()) == (409, REPLACED)
    assert tuple(someone.text_row()) == ("found", A_PDF_TEXT, None)
    assert tuple(someone_else.text_row()) == ("found", A_PDF_TEXT, None)


@pytest.mark.parametrize(
    ("text", "kind", "message"),
    [
        (f"{CHECKED}\ud800", "resume_text_invalid_text", "The resume text must be valid text"),
        (
            f"{CHECKED}\x07",
            "resume_text_control_character",
            "The resume text cannot contain control characters other than line breaks and tabs",
        ),
        (
            f"{CHECKED}‮",
            "resume_text_direction_control",
            "The resume text cannot contain text direction controls",
        ),
        (" \n\t​ ", "resume_text_blank", "The resume text cannot be blank"),
        (
            "x" * 15_001,
            "resume_text_too_long",
            "The resume text can be at most 15,000 characters",
        ),
    ],
    ids=["not text", "a control", "a direction control", "blank", "too long"],
)
async def test_a_save_that_breaks_a_rule_is_refused_by_name_quoting_nothing(
    service: Service, someone: Someone, text: str, kind: str, message: str
) -> None:
    read = await uploaded(service, someone)

    saved = await save(service, someone, {"text": text, "uploaded_at": read["uploaded_at"]})

    assert saved.status_code == 422
    assert problems(saved) == [(kind, ["body", "text"], message)]
    assert CHECKED not in saved.text
    assert tuple(someone.text_row()) == ("found", A_PDF_TEXT, None)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"text": CHECKED}, [("missing", ["body", "uploaded_at"])]),
        (
            {"text": CHECKED, "uploaded_at": "2026-11-07T15:04:05"},
            [("timezone_aware", ["body", "uploaded_at"])],
        ),
        (
            {"text": CHECKED, "uploaded_at": "2026-11-07T15:04:05Z", "state": "found"},
            [("extra_forbidden", ["body", "state"])],
        ),
        ({"uploaded_at": "2026-11-07T15:04:05Z", "text": 7}, [("string_type", ["body", "text"])]),
    ],
    ids=["no upload time", "an upload time with no zone", "a key too many", "text not a string"],
)
async def test_a_body_of_another_shape_is_refused(
    service: Service, someone: Someone, body: dict[str, Any], expected: list[tuple[str, list[str]]]
) -> None:
    await uploaded(service, someone)

    saved = await save(service, someone, body)

    assert saved.status_code == 422
    assert [(kind, where) for kind, where, _ in problems(saved)] == expected


async def test_the_longest_save_fits_the_body_cap_in_four_byte_characters(
    service: Service, someone: Someone
) -> None:
    read = await uploaded(service, someone)
    longest = "\U0001f600" * 15_000
    body = json.dumps({"text": longest, "uploaded_at": read["uploaded_at"]}, ensure_ascii=False)
    sent = body.encode()
    assert len(sent) > 60_000

    saved = await service.client.put(
        "/resume/text",
        headers={**someone.headers, "Content-Type": "application/json"},
        content=sent,
    )

    assert saved.status_code == 200
    assert saved.json()["text"] == longest


async def test_the_text_is_in_no_log_line_across_an_upload_and_a_save(
    service: Service, someone: Someone, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        read = await uploaded(service, someone)
        await save(service, someone, {"text": CHECKED, "uploaded_at": read["uploaded_at"]})
        await save(service, someone, {"text": "x" * 15_001, "uploaded_at": read["uploaded_at"]})

    # The store's client logs the request it sends at debug, the file with it;
    # the service never writes those lines, so only its own and louder ones count.
    shown = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.INFO or record.name.startswith("job_board")
    ]
    lines = [line for line in [*A_PDF_TEXT.splitlines(), *CHECKED.splitlines()] if line]
    for line in [*lines, "x" * 100]:
        assert not any(line in message for message in shown), line


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_both_routes_need_a_signed_in_person(method: str, service: Service) -> None:
    response = await service.client.request(
        method, "/resume/text", json={"text": CHECKED, "uploaded_at": "2026-11-07T15:04:05Z"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_both_routes_answer_503_without_resume_storage(
    method: str, migrated_database_url: str, someone: Someone
) -> None:
    async with service_for(migrated_database_url) as service:
        response = await service.client.request(
            method,
            "/resume/text",
            headers=someone.headers,
            json={"text": CHECKED, "uploaded_at": "2026-11-07T15:04:05Z"},
        )

    assert (response.status_code, response.json()) == (503, NOT_SET_UP)


def test_the_description_declares_each_answer() -> None:
    paths = create_app(make_settings()).openapi()["paths"]

    read, saved = paths["/resume/text"]["get"], paths["/resume/text"]["put"]

    assert set(read["responses"]) == {"200", "401", "404", "503"}
    assert set(saved["responses"]) == {"200", "401", "404", "409", "422", "503"}
    problem = saved["responses"]["422"]["content"]["application/json"]["schema"]
    assert problem == {"$ref": "#/components/schemas/TextRefused"}
