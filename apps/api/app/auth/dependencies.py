from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.models import User
from app.auth.security import verify_access_token
from app.database import get_session
from app.schemas import ApiException


def _auth_error(code: str = "AUTH_REQUIRED", message: str = "A valid bearer token is required.") -> ApiException:
    return ApiException(status_code=status.HTTP_401_UNAUTHORIZED, code=code, message=message)


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: Session = Depends(get_session),
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise _auth_error()
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _auth_error()

    payload = verify_access_token(token)
    if payload is None:
        raise _auth_error("AUTH_INVALID_TOKEN", "Bearer token is invalid or expired.")

    user = session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == UUID(str(payload["sub"])))
    )
    if user is None or not user.is_active:
        raise _auth_error("AUTH_INVALID_TOKEN", "Bearer token is invalid or expired.")
    return user


def _has_any_role(user: User, allowed_roles: set[str]) -> bool:
    user_roles = {role.name for role in user.roles}
    return bool(user_roles & allowed_roles)


def require_roles(*roles: str) -> Callable[[User], User]:
    allowed_roles = set(roles)

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if allowed_roles and not _has_any_role(current_user, allowed_roles):
            raise ApiException(
                status_code=status.HTTP_403_FORBIDDEN,
                code="AUTH_FORBIDDEN",
                message="User does not have permission for this operation.",
            )
        return current_user

    return dependency


def require_trader(current_user: User = Depends(get_current_user)) -> User:
    if not _has_any_role(current_user, {"admin", "trader"}):
        raise ApiException(
            status_code=status.HTTP_403_FORBIDDEN,
            code="AUTH_FORBIDDEN",
            message="User does not have permission for this operation.",
        )
    return current_user


def require_viewer(current_user: User = Depends(get_current_user)) -> User:
    if not _has_any_role(current_user, {"admin", "trader", "viewer"}):
        raise ApiException(
            status_code=status.HTTP_403_FORBIDDEN,
            code="AUTH_FORBIDDEN",
            message="User does not have permission for this operation.",
        )
    return current_user
