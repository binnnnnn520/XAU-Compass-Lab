# XAU Compass Lab

[简体中文](README.md) | English

A gold-news research and paper-trading tool connecting news, market data, features, signals, backtesting, and simulated execution in an inspectable research workflow.

Use it to learn financial data engineering, investigate gold-news strategies, and test trading hypotheses. The current focus is open-source research and local use; paid-product deployment and real-money trading are paused.

## Capabilities

- Ingest news and market data, track source health, and configure multiple providers and failover.
- Analyze news sentiment, scores, and event tags with rules or an optional external LLM API.
- Compute technical, sentiment, time, and available macro-data features; use rules, fitted model artifacts, and strategy ensembles.
- Run bar-by-bar backtests and bounded parameter optimization, producing research metrics.
- Simulate orders and positions with virtual funds, stops, exposure limits, and circuit breakers.
- Inspect news, signals, backtests, paper trading, and risk events in the Web UI.
- Use authentication, structured logs, metrics, backups, and optional disaster-recovery tools.

```text
News and market data → Analysis → Features → Signals → Backtest / Paper trading → Risk and review
```

## Boundaries

- News-sentiment classification accuracy is not gold-price prediction accuracy.
- Models require suitable data and fitted artifacts. Missing models or insufficient calibration samples retain safe fallback behavior.
- Fixtures and paper-trading results do not establish sustained profitability. Research still needs independent data, trading costs, slippage, and market-regime coverage.
- IBKR paper-account tooling is retained but disabled by default. Real-money trading is not enabled.
- The formal 14-day production gray-release window has not been executed. Phase 5 remains paused and unaccepted.

## Quick start

Docker and Docker Compose are required. Frontend development uses Node.js 22; backend development requires Python 3.13 or newer.

Clone the repository and create local configuration in PowerShell:

```powershell
git clone https://github.com/binnnnnn520/XAU-Compass-Lab.git
Set-Location XAU-Compass-Lab
Copy-Item .env.example .env
```

Edit `.env` to replace the PostgreSQL, Redis, Grafana, and `AUTH_TOKEN_SECRET` placeholders. Update `DATABASE_URL` and `REDIS_URL` accordingly. Do not use placeholder passwords. LLM analysis is disabled by default; rule-based analysis requires no API key.

Build the applications and initialize the database:

```powershell
docker compose build api web
docker compose up -d postgres redis
docker compose run --rm api python -m alembic upgrade head
```

Create your login account using the first-administrator instructions in the [startup guide](docs/startup_guide.md), then start the research services:

```powershell
docker compose up -d api worker beat web flower
```

| Surface | Default URL |
| --- | --- |
| Web UI | http://localhost:3000 |
| API health | http://localhost:8000/api/v1/health |
| Interactive API schema | http://localhost:8000/docs |
| Celery Flower | http://localhost:5555 |

News and market availability depends on external providers and their limits. Default providers are configuration examples and can be replaced through environment variables. A successful startup does not mean all external data has already been collected.

## Optional LLM analysis

Configure `LLM_ANALYSIS_ENABLED`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_ENDPOINT_URL`, and `LLM_PROVIDER` in your local `.env`. The example uses ModelScope's OpenAI-compatible API; the implementation also supports Anthropic request formatting.

LLM calls include caching, batching, retries, and budget controls. Missing credentials, failed requests, or an exhausted budget fall back to rules. The budget is an internal estimate rather than the provider's invoice; external usage belongs to your own provider account.

## Stack and development

- API: FastAPI, SQLAlchemy, Alembic, PostgreSQL.
- Background jobs: Celery, Redis.
- Web: Next.js, React, TypeScript.
- Research: rule strategies, scikit-learn model interfaces, Optuna, optional probability calibration.
- Monitoring: Flower, Prometheus, Grafana.

Run API tests in the project Python environment with an isolated PostgreSQL database and a valid `DATABASE_URL`. Tests create and clean up their own schema.

```powershell
python -m pytest apps/api/tests/ -q -p no:cacheprovider
npm ci --prefix apps/web
npm --prefix apps/web run test
npm --prefix apps/web run build
```

## Documentation

- [Startup, configuration, and first login](docs/startup_guide.md)
- [Architecture](docs/architecture/01_overview.md) and [modules](docs/architecture/02_modules.md)
- [Database design](docs/architecture/03_database.md) and [REST API](docs/architecture/04_api.md)
- [Risk and engineering constraints](docs/architecture/05_tasks_risk.md)
- [Project status and research limitations](docs/production_upgrade_status.md)
- [Release verification](docs/release_verification.md)
- [Contributing](CONTRIBUTING.md)

Advanced runbooks live under `docs/operations/`. Their procedures are opt-in and are not part of default startup.

## License

Project code is licensed under [MIT](LICENSE). Third-party dependencies retain their own licenses; news, market data, and external model services are subject to their providers' terms. This project does not ship a redistributable real-time market-data or full-text news dataset.
