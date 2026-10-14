# Repository Guidelines

## Project scope

XAU Compass Lab is a gold-news research and paper-trading project. Preserve the research loop, paper execution, and operator interface. Paid-product deployment and real-money rollout are outside the current scope.

Phase 5 production acceptance is paused and remains unaccepted. Do not start a gray-release window, enable broker execution, or deploy a service without a separate operator instruction.

## Documentation

Read `README.md` or `README.en.md`, `docs/startup_guide.md`, `docs/production_upgrade_status.md`, and the relevant architecture or operations guide. Current code and documented REST contracts define behavior; historical acceptance is not proof of profitability.

Keep both READMEs consistent. Use repository-relative paths and generic local configuration instead of personal machine paths, accounts, or server addresses.

## Engineering contracts

- All datetimes are timezone-aware UTC.
- Persisted prices and money use `Decimal` and `Numeric`, never float.
- `signals.features_used` is mandatory.
- `audit_logs` are append-only; never add update or delete operations.
- Backtests progress bar-by-bar.
- `compute_features(...)` filters strictly before the requested timestamp.
- Paper, backtest, and optional broker paths share feature and signal entry points.
- REST uses `/api/v1`, a unified envelope, and consistent errors and pagination.
- The frontend consumes backend contracts rather than inventing endpoints.
- News deduplication remains `UNIQUE(title_hash, source_id)`; LLM caching does not replace it.

## Development

- Make focused changes and preserve the working baseline.
- Use the project's Python environment, not unrelated environments.
- Never commit environment files, credentials, runtime databases, logs, or downloaded model artifacts.
- Use existing pytest and web test suites, and report actual results.
- Do not rewrite unrelated code or claim acceptance from an unexecuted check.

## Delivery report

Report changed files, commands, tests, satisfied acceptance items, and remaining gaps. Reviews distinguish contract issues, UTC/time leakage, schema/API inconsistencies, missing evidence, and the final decision.
