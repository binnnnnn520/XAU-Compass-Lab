# Project Status / 项目状态

Last updated: 2026-10-14

## Current direction / 当前方向

XAU Compass Lab is an open-source gold-news research and paper-trading project. Paid-product deployment and the formal 14-day gray-release acceptance window are deferred by operator decision.

项目当前用于开源研究和模拟交易。收费产品上线、真实资金交易以及正式14天灰度验收均暂停。

## Implemented capabilities / 已有能力

| Area | Engineering state | Evidence boundary |
| --- | --- | --- |
| News and market ingestion | Implemented, with source health and failover | Availability depends on configured external providers |
| News analysis | Rules and optional external LLM API | Sentiment classification is not a gold-price forecast |
| Features and signals | UTC-safe features, rules, model loading, ensembles, optional calibration | Models and calibration require suitable data and fitted artifacts |
| Backtesting and optimization | Bar-by-bar backtesting and bounded optimization | Fixtures verify behavior, not sustained trading alpha |
| Paper trading and risk | Orders, positions, stops, circuit breaker, audit trail | Paper execution does not establish real-money execution quality |
| Operator interface | Dashboard, news, signals, backtests, paper trading, risk operations | Local use requires configured services and a user account |
| Infrastructure | Authentication, logs, metrics, CI, backup, DR support | Fresh-clone validation is required for releases |
| IBKR paper readiness | Guarded adapter and verification tooling retained | Disabled by default; live broker placeholders remain unusable |

The predecessor repository contains engineering acceptance for Phases 1-4 and IBKR paper-account observations. Historical records remain there and are not imported as this repository's Git history.

原仓库的 Phase 1-4 工程验收和 IBKR 模拟账户记录保留在原仓库。本项目通过自己的测试与发布检查记录当前可复现性。

## Deferred production acceptance / 暂停的上线验收

Phase 5 is **paused and not accepted**. Outstanding evidence is not a prerequisite for publishing research code:

- A declared UTC-bounded continuous 14-day gray-release window.
- Valid paper/live Sharpe comparison, zero-risk-event evidence, and controlled promotion evidence.
- A signed strategy report based on that window.
- Real-money rollout and product deployment.

Do not mark these items passed or start the formal window automatically. Collection and IBKR paper execution remain disabled in the example configuration. Advanced runbooks describe opt-in procedures rather than completed acceptance.

## Scientific limitations / 研究证据边界

- A working API integration does not establish predictive value.
- The recorded walk-forward fixture contains 12 supplied probability/return pairs. Its metrics verify the harness, not a trained strategy's independent out-of-sample performance.
- Longer representative datasets, independent model evaluation, costs, slippage, and market-regime coverage remain research work.
- Missing models or insufficient calibration data retain existing safe fallback behavior.

## Release verification / 发布验证

See [release verification](release_verification.md) for actual checks. Current CI results are available in the repository's Actions tab. Unexecuted checks are never counted as passing.
