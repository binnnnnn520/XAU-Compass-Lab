# XAU Compass Lab API

FastAPI backend for gold-news research, bar-by-bar backtesting, paper trading, and risk operations.

- REST base: `/api/v1`.
- Interactive API schema: `/docs` after local startup.
- PostgreSQL migrations: `python -m alembic upgrade head` from this directory.
- API regression: `python -m pytest tests/ -q` with an isolated PostgreSQL database.
- Authentication uses access/refresh tokens and viewer/trader/admin roles.
- Optional LLM calls use configured external APIs; real-money execution stays disabled.

See the [Chinese README](../../README.md), [English README](../../README.en.md), and [startup guide](../../docs/startup_guide.md) for configuration and first-user initialization.
