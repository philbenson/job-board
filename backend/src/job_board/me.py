"""``GET /me``: who the backend says the signed-in person is."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from job_board.models import Person
from job_board.people import current_person

router = APIRouter()


class Me(BaseModel):
    id: int


class Refused(BaseModel):
    detail: str


@router.get("/me", responses={401: {"model": Refused, "description": "No valid session token"}})
async def me(person: Annotated[Person, Depends(current_person)]) -> Me:
    return Me(id=person.id)
