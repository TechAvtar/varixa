"""Ownership checks. Every analysis-scoped operation must go through here.

A non-owner gets the same 404 as a missing resource so existence is never leaked.
"""

import uuid
from typing import Protocol

from app.enums import UserRole
from app.models import User
from app.utils.errors import NotFoundError

ANALYSIS_NOT_FOUND = "Analysis not found."


class Owned(Protocol):
    user_id: uuid.UUID


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def assert_can_access(user: User, resource: Owned | None, *, message: str) -> None:
    if resource is None or (resource.user_id != user.id and not is_admin(user)):
        raise NotFoundError(message)


def assert_owns_analysis(user: User, analysis: Owned | None) -> None:
    assert_can_access(user, analysis, message=ANALYSIS_NOT_FOUND)
