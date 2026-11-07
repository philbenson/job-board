"""``/resume``: upload, read and remove the signed-in person's one resume.

The file goes to the resume store under a key made from the person's id, the
same for every upload, and a row records its size and when it was uploaded.
Reading answers from the row alone; the file is never served back from here.

Invariant: no database transaction or connection is held while the file
arrives or the store answers, so a slow upload or store never ties up the
pool. The sign-in's work is committed before the body is read.

The upload is the raw PDF as the request body, so no byte of it is read until
the sign-in and the storage checks have passed; see ``upload``.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.models import Person, ResumeRow
from job_board.people import SIGN_IN_REQUIRED, Refused, current_person
from job_board.resumes.store import ResumeStore, StoreDidNotAnswer
from job_board.resumes.upload import read_pdf

NOT_SET_UP = "Resume storage is not set up"
DID_NOT_ANSWER = "Resume storage did not answer; try again later"

STORAGE_ANSWERS: dict[int | str, dict[str, Any]] = {
    503: {"model": Refused, "description": "Resume storage is not set up, or did not answer"},
}

router = APIRouter()


class SavedResume(BaseModel):
    size_bytes: int
    uploaded_at: datetime


class Resume(BaseModel):
    """The signed-in person's resume, or null before their first upload."""

    resume: SavedResume | None


def resume_store(request: Request) -> ResumeStore:
    """The store, or 503 when the service runs without one."""
    store: ResumeStore | None = request.app.state.resume_store
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_SET_UP)
    return store


def object_key(person: Person) -> str:
    return f"resumes/{person.id}.pdf"


def did_not_answer() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DID_NOT_ANSWER)


@router.get("/resume", responses={**SIGN_IN_REQUIRED, **STORAGE_ANSWERS})
async def read_resume(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _store: Annotated[ResumeStore, Depends(resume_store)],
) -> Resume:
    row = await session.scalar(select(ResumeRow).where(ResumeRow.person_id == person.id))
    if row is None:
        return Resume(resume=None)
    return Resume(resume=SavedResume(size_bytes=row.size_bytes, uploaded_at=row.uploaded_at))


@router.put(
    "/resume",
    responses={
        **SIGN_IN_REQUIRED,
        400: {"model": Refused, "description": "The file ended before its declared length"},
        411: {"model": Refused, "description": "No declared length"},
        413: {"model": Refused, "description": "Over 5 MB, or longer than declared"},
        415: {"model": Refused, "description": "Not sent as a PDF, or not a PDF"},
        **STORAGE_ANSWERS,
    },
    # The body is read by the route itself, so it is described here.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_resume(
    request: Request,
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ResumeStore, Depends(resume_store)],
) -> Resume:
    """Stores the PDF in the body as the signed-in person's resume, replacing any before it."""
    await session.commit()  # hold nothing open while the file arrives or the store answers
    file = await read_pdf(request)
    key = object_key(person)
    try:
        await store.put(key, file)
    except StoreDidNotAnswer:
        raise did_not_answer() from None

    # The file is written before the row, each on its own, and a removal
    # deletes the file before the row. So two requests at once by one person,
    # in two tabs say, can leave the row out of step with the store until the
    # next upload or removal: two uploads can leave the row describing the
    # other file, and an upload beside a removal can leave a row whose file
    # the removal deleted, or a file with no row. That is accepted for one
    # person's own resume.
    upsert = insert(ResumeRow).values(
        person_id=person.id, object_key=key, size_bytes=len(file), uploaded_at=func.now()
    )
    row = await session.scalar(
        upsert.on_conflict_do_update(
            index_elements=[ResumeRow.person_id],
            set_={
                "object_key": upsert.excluded.object_key,
                "size_bytes": upsert.excluded.size_bytes,
                "uploaded_at": upsert.excluded.uploaded_at,
            },
        ).returning(ResumeRow)
    )
    await session.commit()
    assert row is not None  # an upsert always returns its row
    return Resume(resume=SavedResume(size_bytes=row.size_bytes, uploaded_at=row.uploaded_at))


@router.delete(
    "/resume",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SIGN_IN_REQUIRED, **STORAGE_ANSWERS},
)
async def remove_resume(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    store: Annotated[ResumeStore, Depends(resume_store)],
) -> Response:
    """Deletes the file, whether or not a row describes it, then the row.

    So a removal also clears a file whose row was never written; if the store
    does not answer, the row stays and still describes the file.
    """
    await session.commit()  # hold nothing open while the store answers
    try:
        await store.delete(object_key(person))
    except StoreDidNotAnswer:
        raise did_not_answer() from None
    await session.execute(delete(ResumeRow).where(ResumeRow.person_id == person.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
