import uuid
from dataclasses import dataclass

import pytest

from app.enums import UserRole
from app.models import User
from app.services.authorization import assert_owns_analysis
from app.utils.errors import NotFoundError


@dataclass
class FakeAnalysis:
    user_id: uuid.UUID


def user(role: str = UserRole.USER) -> User:
    u = User(email=f"{uuid.uuid4()}@example.com", role=role)
    u.id = uuid.uuid4()
    return u


def test_owner_may_access() -> None:
    owner = user()
    assert_owns_analysis(owner, FakeAnalysis(user_id=owner.id))


def test_other_user_gets_not_found_not_forbidden() -> None:
    owner, intruder = user(), user()
    with pytest.raises(NotFoundError):
        assert_owns_analysis(intruder, FakeAnalysis(user_id=owner.id))


def test_missing_resource_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        assert_owns_analysis(user(), None)


def test_admin_may_access_any() -> None:
    owner = user()
    assert_owns_analysis(user(UserRole.ADMIN), FakeAnalysis(user_id=owner.id))
