"""Idempotent Phase 5 soak/evidence setup.

Ensures two operational prerequisites for the gray-release evidence run:

1. An ``admin`` user (so the admin-only ``/api/v1/live/gray-release-report``
   endpoint can be queried by verification commands and the daily snapshot job).
2. An active ``StrategyRun`` whose sentiment thresholds are calibrated to a
   range the live analyzer actually reaches, so the rule strategy produces
   BUY/SELL signals (and therefore paper orders + parallel observations)
   instead of perpetual HOLD. Threshold changes are recorded in
   ``StrategyRun.parameters`` (traceable, per the model-lifecycle contract).

Run inside the api image (WORKDIR ``/workspace/apps/api``):

    docker compose run --rm \
      -e PHASE5_ADMIN_USERNAME=admin \
      -e PHASE5_ADMIN_PASSWORD='<strong-password>' \
      -e PHASE5_SENTIMENT_POSITIVE_THRESHOLD=0.2000 \
      -e PHASE5_SENTIMENT_NEGATIVE_THRESHOLD=-0.2000 \
      api python scripts/phase5_soak_setup.py

The script is safe to re-run: it updates thresholds on the existing active
strategy and only creates the admin user when missing.
"""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.database import SessionLocal, get_engine
from app.models import StrategyRun
from app.services.signal_engine.rule_strategy import (
    DEFAULT_STRATEGY_NAME,
    DEFAULT_STRATEGY_PARAMETERS,
    DEFAULT_STRATEGY_VERSION,
)


def ensure_admin(session: Session) -> None:
    username = os.getenv("PHASE5_ADMIN_USERNAME", "admin")
    password = os.getenv("PHASE5_ADMIN_PASSWORD")

    existing = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        if not any(role.name == "admin" for role in existing.roles):
            existing.roles.append(Role(name="admin"))
            session.flush()
            print(f"admin_role_added user={username}")
        else:
            print(f"admin_exists user={username}")
        return

    if not password:
        raise SystemExit("PHASE5_ADMIN_PASSWORD is required to create the admin user")

    user = User(
        username=username,
        password_hash=hash_password(password),
        is_active=True,
        roles=[Role(name="admin")],
    )
    session.add(user)
    session.flush()
    print(f"admin_created user={username}")


def ensure_tuned_strategy(session: Session) -> None:
    positive = os.getenv("PHASE5_SENTIMENT_POSITIVE_THRESHOLD", "0.2000")
    negative = os.getenv("PHASE5_SENTIMENT_NEGATIVE_THRESHOLD", "-0.2000")

    active = session.execute(
        select(StrategyRun).where(StrategyRun.is_active.is_(True)).order_by(StrategyRun.created_at.asc())
    ).scalars().all()

    if active:
        for strategy in active:
            params = dict(strategy.parameters or {})
            params["positive_sentiment_threshold"] = positive
            params["negative_sentiment_threshold"] = negative
            strategy.parameters = params
        session.flush()
        print(f"strategy_thresholds_updated count={len(active)} positive={positive} negative={negative}")
        return

    params = dict(DEFAULT_STRATEGY_PARAMETERS)
    params["positive_sentiment_threshold"] = positive
    params["negative_sentiment_threshold"] = negative
    strategy = StrategyRun(
        strategy_name=DEFAULT_STRATEGY_NAME,
        version=DEFAULT_STRATEGY_VERSION,
        parameters=params,
        description="Phase 5 soak strategy: rule sentiment/momentum with calibrated sentiment thresholds.",
        is_active=True,
    )
    session.add(strategy)
    session.flush()
    print(f"strategy_created name={DEFAULT_STRATEGY_NAME} positive={positive} negative={negative}")


def main() -> None:
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    session = SessionLocal()
    try:
        ensure_admin(session)
        ensure_tuned_strategy(session)
        session.commit()
        print("phase5_soak_setup_done")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
