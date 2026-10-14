from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload


API_ROOT = Path(__file__).resolve().parents[1]

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.database import get_session
from app.main import app
from app.models import MarketBar, NewsItem, NewsSource, StrategyRun


def _seed_user(db_session, *, username: str, password: str, roles: list[str], is_active: bool = True) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        is_active=is_active,
        roles=[Role(name=role) for role in roles],
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


async def _request(
    db_session,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, object] | None = None,
) -> httpx.Response:
    def override_db():
        yield db_session

    app.dependency_overrides[get_session] = override_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, headers=headers, json=json)
    finally:
        app.dependency_overrides.clear()


def _login_token(db_session, *, username: str, password: str) -> str:
    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _login_tokens(db_session, *, username: str, password: str) -> dict[str, str]:
    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
    )
    assert response.status_code == 200
    data = response.json()["data"]
    return {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}


def test_login_returns_access_token_for_active_user(db_session) -> None:
    _seed_user(db_session, username="phase3_trader", password="correct horse battery staple", roles=["trader"])

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/login",
            json={"username": "phase3_trader", "password": "correct horse battery staple"},
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["token_type"] == "bearer"
    assert payload["data"]["access_token"].count(".") == 2
    assert payload["data"]["refresh_token"].count(".") == 2
    assert payload["data"]["access_token"] != payload["data"]["refresh_token"]
    assert payload["data"]["user"]["username"] == "phase3_trader"
    assert payload["data"]["user"]["roles"] == ["trader"]


def test_refresh_token_returns_new_access_token(db_session) -> None:
    _seed_user(db_session, username="phase3_refresh_viewer", password="viewer-password", roles=["viewer"])
    tokens = _login_tokens(db_session, username="phase3_refresh_viewer", password="viewer-password")

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["token_type"] == "bearer"
    assert payload["data"]["access_token"].count(".") == 2
    assert payload["data"]["access_token"] != tokens["refresh_token"]

    protected_response = asyncio.run(
        _request(
            db_session,
            "GET",
            "/api/v1/news",
            headers={"Authorization": f"Bearer {payload['data']['access_token']}"},
        )
    )
    assert protected_response.status_code == 200


def test_refresh_token_cannot_access_viewer_protected_endpoint(db_session) -> None:
    _seed_user(db_session, username="phase3_refresh_only_viewer", password="viewer-password", roles=["viewer"])
    tokens = _login_tokens(db_session, username="phase3_refresh_only_viewer", password="viewer-password")

    response = asyncio.run(
        _request(
            db_session,
            "GET",
            "/api/v1/news",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "AUTH_INVALID_TOKEN"


def test_login_wrong_password_returns_unified_401(db_session) -> None:
    _seed_user(db_session, username="phase3_viewer", password="right-password", roles=["viewer"])

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/login",
            json={"username": "phase3_viewer", "password": "wrong-password"},
        )
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_news_list_rejects_missing_bearer_token(db_session) -> None:
    response = asyncio.run(_request(db_session, "GET", "/api/v1/news"))

    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "AUTH_REQUIRED"


def test_viewer_bearer_token_allows_news_list(db_session) -> None:
    _seed_user(db_session, username="phase3_news_viewer", password="viewer-password", roles=["viewer"])
    db_session.add(
        NewsItem(
            source=NewsSource(
                name="Auth Fixture Source",
                source_type="rss",
                url="https://example.com/auth-fixture.xml",
            ),
            title="Gold steadies as traders await Fed decision",
            summary="Fixture news item for auth route coverage.",
            published_at=datetime(2026, 4, 2, 9, 0, tzinfo=UTC),
            title_hash="7" * 64,
            status="pending",
        )
    )
    db_session.commit()
    token = _login_token(db_session, username="phase3_news_viewer", password="viewer-password")

    response = asyncio.run(
        _request(
            db_session,
            "GET",
            "/api/v1/news",
            headers={"Authorization": f"Bearer {token}"},
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["total"] == 1


def test_viewer_bearer_token_cannot_create_backtest(db_session) -> None:
    _seed_user(db_session, username="phase3_backtest_viewer", password="viewer-password", roles=["viewer"])
    strategy = StrategyRun(
        strategy_name="auth_forbidden_backtest_v1",
        version="1.0.0",
        parameters={"lookback_hours": 1, "momentum_bars": 1},
        is_active=True,
    )
    db_session.add(strategy)
    db_session.commit()
    token = _login_token(db_session, username="phase3_backtest_viewer", password="viewer-password")

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/backtest",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "strategy_run_id": str(strategy.id),
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
                "initial_capital": "1000.00",
                "slippage_bps": 0,
                "commission_bps": 0,
            },
        )
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "AUTH_FORBIDDEN"


def test_protected_write_endpoint_rejects_missing_bearer_token(db_session) -> None:
    strategy = StrategyRun(
        strategy_name="auth_backtest_v1",
        version="1.0.0",
        parameters={"lookback_hours": 1, "momentum_bars": 1},
        is_active=True,
    )
    db_session.add(strategy)
    db_session.commit()

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/backtest",
            json={
                "strategy_run_id": str(strategy.id),
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
                "initial_capital": "1000.00",
                "slippage_bps": 0,
                "commission_bps": 0,
            },
        )
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "AUTH_REQUIRED"


def test_roles_are_persisted_as_strings_and_user_datetimes_are_utc(db_session) -> None:
    user = _seed_user(db_session, username="phase3_admin", password="admin-password", roles=["admin", "trader"])

    db_session.expire_all()
    persisted = db_session.get(User, user.id)

    assert persisted is not None
    assert [role.name for role in persisted.roles] == ["admin", "trader"]
    assert all(isinstance(role.name, str) for role in persisted.roles)
    assert persisted.created_at.tzinfo is not None
    assert persisted.created_at.utcoffset() == UTC.utcoffset(datetime(2026, 4, 30, tzinfo=UTC))
    assert persisted.updated_at.tzinfo is not None
    assert persisted.updated_at.utcoffset() == UTC.utcoffset(datetime(2026, 4, 30, tzinfo=UTC))


def test_register_rejects_viewer_token(db_session) -> None:
    _seed_user(db_session, username="phase3_register_viewer", password="viewer-password", roles=["viewer"])
    token = _login_token(db_session, username="phase3_register_viewer", password="viewer-password")

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "phase3_viewer_created_user",
                "password": "created-password",
                "roles": ["viewer"],
                "is_active": True,
            },
        )
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "AUTH_FORBIDDEN"


def test_register_admin_token_creates_user_roles_and_utc_datetimes(db_session) -> None:
    _seed_user(db_session, username="phase3_register_admin", password="admin-password", roles=["admin"])
    token = _login_token(db_session, username="phase3_register_admin", password="admin-password")

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "phase3_registered_trader",
                "password": "registered-password",
                "roles": ["trader", "viewer"],
                "is_active": True,
            },
        )
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["username"] == "phase3_registered_trader"
    assert payload["data"]["roles"] == ["trader", "viewer"]
    assert payload["data"]["is_active"] is True

    db_session.expire_all()
    persisted = db_session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.username == "phase3_registered_trader")
    )
    assert persisted is not None
    assert [role.name for role in persisted.roles] == ["trader", "viewer"]
    assert persisted.created_at.tzinfo is not None
    assert persisted.created_at.utcoffset() == UTC.utcoffset(datetime(2026, 4, 30, tzinfo=UTC))
    assert persisted.updated_at.tzinfo is not None
    assert persisted.updated_at.utcoffset() == UTC.utcoffset(datetime(2026, 4, 30, tzinfo=UTC))


def test_register_duplicate_username_returns_unified_409(db_session) -> None:
    _seed_user(db_session, username="phase3_duplicate_admin", password="admin-password", roles=["admin"])
    _seed_user(db_session, username="phase3_duplicate_user", password="existing-password", roles=["viewer"])
    token = _login_token(db_session, username="phase3_duplicate_admin", password="admin-password")

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "phase3_duplicate_user",
                "password": "new-password",
                "roles": ["viewer"],
                "is_active": True,
            },
        )
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "CONFLICT"


def test_register_rejects_unknown_role(db_session) -> None:
    _seed_user(db_session, username="phase3_role_admin", password="admin-password", roles=["admin"])
    token = _login_token(db_session, username="phase3_role_admin", password="admin-password")

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "phase3_unknown_role_user",
                "password": "created-password",
                "roles": ["operator"],
                "is_active": True,
            },
        )
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_cors_preflight_allows_configured_origin(db_session) -> None:
    response = asyncio.run(
        _request(
            db_session,
            "OPTIONS",
            "/api/v1/news",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_login_rate_limit_returns_429_envelope(db_session) -> None:
    _seed_user(db_session, username="phase3_limited", password="right-password", roles=["viewer"])

    response = None
    for _ in range(6):
        response = asyncio.run(
            _request(
                db_session,
                "POST",
                "/api/v1/auth/login",
                json={"username": "phase3_limited", "password": "wrong-password"},
            )
        )

    assert response is not None
    assert response.status_code == 429
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "RATE_LIMITED"


def test_trader_bearer_token_allows_protected_backtest_create(db_session) -> None:
    _seed_user(db_session, username="phase3_backtest_trader", password="trade-password", roles=["trader"])
    strategy = StrategyRun(
        strategy_name="auth_allowed_backtest_v1",
        version="1.0.0",
        parameters={"lookback_hours": 1, "momentum_bars": 1},
        is_active=True,
    )
    db_session.add_all(
        [
            strategy,
            MarketBar(
                timeframe="1h",
                bar_time=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
                open=Decimal("100.00000000"),
                high=Decimal("101.00000000"),
                low=Decimal("99.00000000"),
                close=Decimal("100.00000000"),
                volume=Decimal("10.00000000"),
            ),
        ]
    )
    db_session.commit()
    login_response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/auth/login",
            json={"username": "phase3_backtest_trader", "password": "trade-password"},
        )
    )
    token = login_response.json()["data"]["access_token"]

    response = asyncio.run(
        _request(
            db_session,
            "POST",
            "/api/v1/backtest",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "strategy_run_id": str(strategy.id),
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
                "initial_capital": "1000.00",
                "slippage_bps": 0,
                "commission_bps": 0,
            },
        )
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BACKTEST_DATA_INSUFFICIENT"
