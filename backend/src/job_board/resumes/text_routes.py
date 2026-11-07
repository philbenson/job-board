"""``/resume/text``: the text read from the signed-in person's resume, and their check of it.

The upload reads the file's text and keeps what the reading gave beside the
resume's row. Here the person reads it back and saves it checked: corrected,
put in order, or typed in where nothing could be read. A save names the
upload it checked by that upload's time, and is refused once a newer file has
replaced it, so a check never lands on text read from another file.

Neither route logs the text, and a refused save's answer quotes none of it.
"""

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.models import Person, ResumeRow
from job_board.people import SIGN_IN_REQUIRED, Refused, current_person
from job_board.resumes.routes import STORAGE_ANSWERS, resume_store
from job_board.resumes.store import ResumeStore
from job_board.resumes.text_rules import ReadState, checked_resume_text

NO_RESUME = "No resume uploaded"
REPLACED = "Your resume was replaced since this text was read"

router = APIRouter()


class ResumeText(BaseModel):
    """What reading the resume's text gave, and the person's check of it.

    ``state`` is null for a resume uploaded before its text was read.
    """

    uploaded_at: datetime
    state: ReadState | None
    text: str | None
    checked_at: datetime | None


class CheckedText(BaseModel):
    """The text the person checked, and the upload time of the file it was read from."""

    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, AfterValidator(checked_resume_text)]
    uploaded_at: AwareDatetime


class Problem(BaseModel):
    type: str
    loc: list[str | int]
    msg: str


class TextRefused(BaseModel):
    """The app's validation answer: each problem's kind, place and message, quoting nothing."""

    detail: list[Problem]


NO_RESUME_ANSWER: dict[int | str, dict[str, Any]] = {
    404: {"model": Refused, "description": NO_RESUME},
}


def text_of(row: ResumeRow) -> ResumeText:
    # The table's check holds the state to the four a reading gives, or none.
    state = cast("ReadState | None", row.text_state)
    return ResumeText(
        uploaded_at=row.uploaded_at, state=state, text=row.text, checked_at=row.text_checked_at
    )


def no_resume() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_RESUME)


@router.get("/resume/text", responses={**SIGN_IN_REQUIRED, **NO_RESUME_ANSWER, **STORAGE_ANSWERS})
async def read_resume_text(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _store: Annotated[ResumeStore, Depends(resume_store)],
) -> ResumeText:
    row = await session.scalar(select(ResumeRow).where(ResumeRow.person_id == person.id))
    if row is None:
        raise no_resume()
    return text_of(row)


# The declared 422 replaces FastAPI's validation 422 in the API description,
# with the shape the app's one validation answer gives.
@router.put(
    "/resume/text",
    responses={
        **SIGN_IN_REQUIRED,
        **NO_RESUME_ANSWER,
        409: {"model": Refused, "description": REPLACED},
        422: {
            "model": TextRefused,
            "description": "The text breaks one of its rules, or the body is of another shape",
        },
        **STORAGE_ANSWERS,
    },
)
async def save_resume_text(
    body: CheckedText,
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _store: Annotated[ResumeStore, Depends(resume_store)],
) -> ResumeText:
    """Saves the person's checked text over what the reading gave, keeping the reading's state.

    It saves only while the resume is still the upload the text was read
    from; the reading's state stays, so the screen can still say how it went.
    """
    row = await session.scalar(
        update(ResumeRow)
        .where(ResumeRow.person_id == person.id, ResumeRow.uploaded_at == body.uploaded_at)
        .values(text=body.text, text_checked_at=func.now())
        .returning(ResumeRow)
    )
    if row is None:
        has_resume = await session.scalar(
            select(ResumeRow.person_id).where(ResumeRow.person_id == person.id)
        )
        if has_resume is None:
            raise no_resume()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=REPLACED)
    await session.commit()
    return text_of(row)
