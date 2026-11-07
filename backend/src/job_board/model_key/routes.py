"""``/model-key``: read, save and remove the signed-in person's own model key.

Invariant: the key leaves the service only toward Anthropic. It arrives as a
secret, goes to the checker and into the seal, and nothing answered or logged
here carries it: a saved key shows only its last four characters.

Invariant: no database transaction or connection is held while Anthropic is
asked, so a slow check never ties up the pool. The session's work up to the
check is committed first.

Nothing is written unless the check accepts the key; a refused key leaves an
earlier one in place.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from job_board.database import get_session
from job_board.model_key.check import KeyChecker, get_key_checker
from job_board.model_key.sealing import seal
from job_board.models import ModelKey, Person
from job_board.people import SIGN_IN_REQUIRED, Refused, current_person, get_settings
from job_board.settings import Settings

Provider = Literal["anthropic"]
RefusalReason = Literal["malformed", "rejected", "not-permitted", "unavailable"]

LONGEST_KEY = 512
# Well above four, so that showing a saved key's last four characters never shows
# most of it, whatever Anthropic accepts.
SHORTEST_KEY = 20
# An HTTP header carries only printable ASCII, and the key travels in one.
KEY_CHARACTERS = frozenset(chr(code) for code in range(0x21, 0x7F))

REFUSALS: dict[RefusalReason, tuple[int, str]] = {
    "malformed": (422, "That does not look like an Anthropic API key."),
    "rejected": (422, "Anthropic did not accept that key."),
    "not-permitted": (422, "That key cannot use the model this app runs."),
    "unavailable": (
        503,
        "Anthropic did not confirm the key, so nothing was saved. Try again later; "
        "if it keeps happening, check the key's limits in the Claude Console.",
    ),
}

router = APIRouter()


class ModelKeyToSave(BaseModel):
    provider: Provider
    key: SecretStr


class SavedModelKey(BaseModel):
    provider: Provider
    last_four: str
    checked_at: datetime


class ModelKeyRefused(BaseModel):
    detail: str
    reason: RefusalReason


def refused(reason: RefusalReason) -> JSONResponse:
    status_code, detail = REFUSALS[reason]
    body = ModelKeyRefused(detail=detail, reason=reason)
    return JSONResponse(status_code=status_code, content=body.model_dump())


def well_formed(key: str) -> bool:
    return SHORTEST_KEY <= len(key) <= LONGEST_KEY and set(key) <= KEY_CHARACTERS


def saved(row: ModelKey) -> SavedModelKey:
    return SavedModelKey(provider="anthropic", last_four=row.last_four, checked_at=row.checked_at)


@router.get(
    "/model-key",
    responses={
        **SIGN_IN_REQUIRED,
        404: {"model": Refused, "description": "No key saved"},
    },
)
async def read_model_key(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedModelKey:
    row = await session.scalar(
        select(ModelKey).where(ModelKey.person_id == person.id, ModelKey.provider == "anthropic")
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no model key saved")
    return saved(row)


# The declared 422 replaces FastAPI's validation 422 in the API description. A
# body FastAPI cannot read at all, such as one missing a field, still gets its
# list-shaped 422, from the app's one validation answer, which never quotes it.
@router.put(
    "/model-key",
    response_model=SavedModelKey,  # a refusal is returned as its own response
    responses={
        **SIGN_IN_REQUIRED,
        422: {"model": ModelKeyRefused, "description": "A malformed key, or one Anthropic refused"},
        503: {"model": ModelKeyRefused, "description": "Anthropic did not confirm the key"},
    },
)
async def save_model_key(
    to_save: ModelKeyToSave,
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    check: Annotated[KeyChecker, Depends(get_key_checker)],
) -> SavedModelKey | JSONResponse:
    key = to_save.key.get_secret_value().strip()
    if not well_formed(key):
        return refused("malformed")

    await session.commit()  # hold nothing open while Anthropic answers
    outcome = await check(key)
    if outcome != "accepted":
        return refused(outcome)

    sealed = seal(
        key,
        person.id,
        to_save.provider,
        service_key=settings.model_key_encryption_key.get_secret_value(),
    )
    upsert = insert(ModelKey).values(
        person_id=person.id,
        provider=to_save.provider,
        sealed_key=sealed,
        last_four=key[-4:],
        checked_at=func.now(),
    )
    upserted = await session.scalars(
        upsert.on_conflict_do_update(
            index_elements=[ModelKey.person_id, ModelKey.provider],
            set_={
                "sealed_key": upsert.excluded.sealed_key,
                "last_four": upsert.excluded.last_four,
                "checked_at": upsert.excluded.checked_at,
                "updated_at": func.now(),
            },
        ).returning(ModelKey)
    )
    row = upserted.one()  # an upsert always returns its row
    await session.commit()
    return saved(row)


@router.delete("/model-key", status_code=status.HTTP_204_NO_CONTENT, responses={**SIGN_IN_REQUIRED})
async def remove_model_key(
    person: Annotated[Person, Depends(current_person)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await session.execute(
        delete(ModelKey).where(ModelKey.person_id == person.id, ModelKey.provider == "anthropic")
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
