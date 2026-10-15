# Development Guidelines / 开发规范

## Project scope

XAU Compass Lab is an open-source gold-news research and paper-trading project. Preserve the research workflow, simulated execution, and operator interface.

Broker submission and observation collection are opt-in tools, disabled by default. Do not enable them, use external accounts, or deploy services as a side effect of development or tests.

## Documentation

Read the [Chinese README](../README.md) or [English README](../README.en.md), [startup guide](startup_guide.md), [capabilities](capabilities.md), and the relevant architecture or operations guide. Current code and documented REST contracts define behavior. Tests establish engineering behavior, not profitability.

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
- Do not rewrite unrelated code or report an unexecuted check as passing.
- Document capabilities, usage, defaults, and limitations without personal development history or private plans.

## Delivery report

For pull requests, report changed files, commands, test results, satisfied requirements, and remaining gaps. Reviews distinguish contract issues, UTC/time leakage, schema/API inconsistencies, missing evidence, and the final decision.
