"""``GET /me``: who the backend says the signed-in person is."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from job_board.models import Person
from job_board.people import SIGN_IN_REQUIRED, current_person

router = APIRouter()


class Me(BaseModel):
    id: int


@router.get("/me", responses={**SIGN_IN_REQUIRED})
async def me(person: Annotated[Person, Depends(current_person)]) -> Me:
    return Me(id=person.id)
