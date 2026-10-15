# Capabilities and Limitations / 功能说明与研究限制

XAU Compass Lab connects gold-related news, market data, strategy research, and paper trading. The default workflow uses local services and virtual funds.

项目将黄金相关新闻、行情、策略研究和模拟交易连接起来，适合学习数据工程、复现研究流程和测试策略想法。默认使用本地服务和虚拟资金。

## Capabilities / 功能

| Area / 模块 | Function / 功能 | Requirements and limits / 使用条件与限制 |
| --- | --- | --- |
| News and market data / 新闻与行情 | Ingestion, source health, provider failover | External provider availability, access limits, and terms apply |
| News analysis / 新闻分析 | Keyword rules and optional external LLM API | Rules need no API key; external LLM calls use your own account |
| Features and signals / 特征与信号 | Time-filtered features, rules, fitted-model loading, ensembles, optional calibration | Models need suitable data and fitted artifacts; insufficient inputs retain safe fallback behavior |
| Backtesting / 回测 | Bar-by-bar simulation and bounded parameter optimization | Results depend on data quality, sample selection, costs, and configuration |
| Paper trading / 模拟交易 | Simulated orders, positions, stops, exposure limits, circuit breaker | Virtual execution is not a measurement of real-money execution quality |
| Web UI / 界面 | Dashboard, news, signals, backtests, paper trading, risk events | Requires configured services and an authenticated local account |
| Infrastructure / 基础设施 | Authentication, logs, metrics, CI, backup, recovery tools | Recovery exercises require isolated databases and volumes |
| Optional IBKR paper tools / 可选券商模拟工具 | Guarded account inspection, dry runs, supervised paper-order checks | Disabled by default; requires a paper account and reachable Gateway/TWS |

## Defaults / 默认设置

- Rule-based analysis works without an LLM key. External LLM analysis is opt-in.
- Broker submission and scheduled broker-observation collection are disabled in `.env.example`.
- The IBKR live broker implementation is a blocked placeholder, not a supported real-money trading connection.
- Model files and provider credentials are not distributed with the project.
- News and market-data availability depends on the sources you configure.

规则分析不需要 LLM 密钥；外部 LLM、券商模拟工具及额外观测采集均需自行选择和配置。仓库不附带模型文件、服务密钥或可直接使用的真实资金交易连接。

## Research limitations / 研究限制

- News-sentiment classification is not a gold-price forecast. An API integration alone does not establish predictive value.
- Test fixtures verify software behavior; they are not independent out-of-sample strategy evidence.
- Evaluate strategies on representative, independent data with realistic costs, slippage, and multiple market regimes.
- Missing models or insufficient calibration data may activate fallback behavior. Inspect the selected strategy, model metadata, and signal reasons before interpreting results.
- Paper results, diagnostic report flags, and passing tests do not establish sustained profitability or authorize real-money trading.

新闻情感不等于价格预测；测试通过不等于策略有效；模拟交易不等于真实成交。研究结论需要独立数据和可复现的评估过程，不能仅凭演示数据、测试指标或接口返回值推断盈利能力。

## Further reading / 相关文档

- [Startup and configuration / 启动与配置](startup_guide.md)
- [Architecture / 架构](architecture/01_overview.md)
- [Testing / 测试与验证](testing.md)
- [Broker sandbox safety / 券商模拟账户安全](operations/broker_safety.md)
