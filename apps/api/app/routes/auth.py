from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_roles
from app.auth.models import Role, User
from app.auth.rate_limit import login_rate_limiter
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_refresh_token,
)
from app.database import get_session
from app.schemas import ApiException, success_response


router = APIRouter(prefix="/auth", tags=["auth"])
ALLOWED_ROLES = {"admin", "trader", "viewer"}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)


class LoginUserData(BaseModel):
    id: str
    username: str
    roles: list[str]


class LoginResponseData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: LoginUserData


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class RefreshResponseData(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)
    roles: list[str] = Field(min_length=1)
    is_active: bool = True


class RegisterResponseData(BaseModel):
    id: str
    username: str
    roles: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


def _rate_limit_key(request: Request, username: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{username.strip().lower()}"


def _rate_limited() -> ApiException:
    return ApiException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        code="RATE_LIMITED",
        message="Too many failed login attempts.",
    )


def _invalid_credentials() -> ApiException:
    return ApiException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="AUTH_INVALID_CREDENTIALS",
        message="Invalid username or password.",
    )


def _invalid_token() -> ApiException:
    return ApiException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="AUTH_INVALID_TOKEN",
        message="Token is invalid or expired.",
    )


def _username_conflict() -> ApiException:
    return ApiException(
        status_code=status.HTTP_409_CONFLICT,
        code="CONFLICT",
        message="Username already exists.",
    )


def _validate_register_roles(roles: list[str]) -> list[str]:
    normalized: list[str] = []
    for role in roles:
        value = role.strip().lower()
        if value not in ALLOWED_ROLES:
            raise ApiException(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="VALIDATION_ERROR",
                message="roles may only contain admin, trader, or viewer.",
            )
        if value not in normalized:
            normalized.append(value)
    return normalized


def _load_active_user(session: Session, user_id: str) -> User | None:
    try:
        parsed_user_id = UUID(str(user_id))
    except (ValueError, TypeError):
        return None
    return session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == parsed_user_id)
    )


def _login_user_data(user: User) -> LoginUserData:
    return LoginUserData(
        id=str(user.id),
        username=user.username,
        roles=[role.name for role in user.roles],
    )


def _register_user_data(user: User) -> RegisterResponseData:
    return RegisterResponseData(
        id=str(user.id),
        username=user.username,
        roles=[role.name for role in user.roles],
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, session: Session = Depends(get_session)):
    key = _rate_limit_key(request, payload.username)
    if login_rate_limiter.is_limited(key):
        raise _rate_limited()

    user = session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.username == payload.username)
    )
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        if login_rate_limiter.record_failure(key):
            raise _rate_limited()
        raise _invalid_credentials()

    login_rate_limiter.clear(key)
    return success_response(
        LoginResponseData(
            access_token=create_access_token(user),
            refresh_token=create_refresh_token(user),
            user=_login_user_data(user),
        )
    )


@router.post("/refresh")
def refresh(payload: RefreshRequest, session: Session = Depends(get_session)):
    token_payload = verify_refresh_token(payload.refresh_token)
    if token_payload is None:
        raise _invalid_token()

    user = _load_active_user(session, str(token_payload["sub"]))
    if user is None or not user.is_active:
        raise _invalid_token()

    return success_response(RefreshResponseData(access_token=create_access_token(user)))


@router.post("/register")
def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
):
    roles = _validate_register_roles(payload.roles)
    existing = session.scalar(select(User.id).where(User.username == payload.username))
    if existing is not None:
        raise _username_conflict()

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_active=payload.is_active,
        roles=[Role(name=role) for role in roles],
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise _username_conflict() from exc

    session.refresh(user)
    return success_response(_register_user_data(user), status_code=status.HTTP_201_CREATED)
