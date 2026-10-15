# REST API / 接口概览

Base path: `/api/v1`. The running FastAPI application's `/docs` and `/openapi.json` describe current request/response schemas. Use those schemas for field-level details and role requirements.

## Conventions

- Standard responses use `success`, `data`, and `error`.
- Collections use documented pagination and filters; clients must not invent fields.
- Datetimes are UTC. Finance values preserve the existing Decimal serialization contract.
- Authenticated requests send `Authorization: Bearer <access_token>`.
- Roles are `viewer`, `trader`, and `admin`; authorization is enforced by each route.
- Validation, authentication, permission, conflict, missing-resource, and rate-limit failures use consistent error codes.

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | PostgreSQL/Redis health |
| POST | `/auth/login` | Local account login; access and refresh tokens |
| POST | `/auth/refresh` | Exchange refresh token for access token |
| POST | `/auth/register` | Admin-only local user creation |
| GET | `/news`, `/news/{news_id}` | News list and detail |
| GET | `/sentiment/aggregate`, `/events` | Aggregated sentiment and events |
| GET | `/signals` | Signal records and feature evidence |
| POST | `/backtest` | Create a backtest |
| GET | `/backtest`, `/backtest/{backtest_id}` | Backtest list and results |
| GET | `/paper/orders`, `/paper/positions`, `/paper/account` | Simulated orders, positions, and account |
| GET | `/risk/events`, `/risk/status` | Risk events and status |
| POST | `/live/emergency-stop` | Guarded emergency-stop operation |
| GET | `/live/gray-release-report` | Read-only optional paper/broker comparison report |
| WebSocket | `/ws/stream` | Authenticated real-time stream |

`/metrics` is an operational endpoint outside the REST base. The Web application proxies backend traffic through its configured local API origin.

## Local accounts

Initialize the first administrator with the [startup guide](../startup_guide.md). Additional accounts are created by an administrator; there is no public self-service registration. Access and refresh tokens have distinct types and uses.

The `/live` namespace exposes optional diagnostics and safety controls. Its name does not imply an enabled real-money broker connection. See [broker sandbox safety](../operations/broker_safety.md) before using the optional tools.
