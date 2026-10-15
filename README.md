# XAU Compass Lab

简体中文 | [English](README.en.md)

黄金新闻驱动的研究与模拟交易工具。把新闻、行情、特征、信号、回测和模拟交易串成一个可以检查与复现的研究流程。

本项目适合学习金融数据工程、研究黄金新闻策略，以及验证策略想法。当前目标是开源研究与本地使用

## 它能做什么

- 采集新闻与行情，记录来源健康状态，支持配置多个来源和故障切换。
- 通过关键词规则或可选的外部 LLM API 分析新闻情感、评分和事件标签。
- 计算技术、情感、时间及已有宏观数据特征，支持规则策略、模型加载和策略组合。
- 逐根 K 线回测，进行有边界的参数优化，并输出研究指标。
- 使用虚拟资金模拟订单与持仓，执行止损、止盈、风险限制与熔断。
- 在 Web 界面查看新闻、信号、回测、模拟交易和风险事件。
- 提供认证、结构化日志、监控指标、备份及可选的灾难恢复工具。

```text
新闻与行情 → 分析 → 特征 → 信号 → 回测 / 模拟交易 → 风控与复盘
```

## 重要边界

- 新闻情感分类准确率不等于金价涨跌预测准确率。
- 模型需要合适的数据和已训练的模型文件；缺失模型或校准样本不足时保留安全回退行为。
- 测试样本和模拟交易结果不能证明长期盈利。研究仍需独立数据、交易成本、滑点和不同市场阶段的评估。
- IBKR 模拟账户相关工具保留但默认关闭；真实资金交易未启用。
- 原生产路线的正式14天灰度窗口未执行，Phase 5 保持“暂停、未验收”。

## 快速开始

需要 Docker 与 Docker Compose。前端开发使用 Node.js 22；后端开发使用 Python 3.13 或更高版本。

克隆仓库，并在 PowerShell 中创建自己的本地配置：

```powershell
git clone https://github.com/binnnnnn520/XAU-Compass-Lab.git
Set-Location XAU-Compass-Lab
Copy-Item .env.example .env
```

编辑 `.env`，替换 PostgreSQL、Redis、Grafana 密码以及 `AUTH_TOKEN_SECRET` 占位符；同步更新 `DATABASE_URL` 和 `REDIS_URL`。不要使用示例占位密码。LLM 默认关闭，不需要 API Key 就能使用规则分析。

构建应用并初始化数据库：

```powershell
docker compose build api web
docker compose up -d postgres redis
docker compose run --rm api python -m alembic upgrade head
```

按照[启动指南](docs/startup_guide.md)的“初始化首个管理员”步骤创建自己的登录账户，然后启动研究服务：

```powershell
docker compose up -d api worker beat web flower
```

| 入口 | 默认地址 |
| --- | --- |
| Web 界面 | http://localhost:3000 |
| API 健康检查 | http://localhost:8000/api/v1/health |
| 交互式 API 文档 | http://localhost:8000/docs |
| Celery Flower | http://localhost:5555 |

新闻和行情是否可用取决于外部来源及其限制。默认来源仅为配置示例，可以通过环境变量替换；启动成功不代表外部数据已经全部采集完成。

## 可选 LLM 分析

在本地 `.env` 中配置 `LLM_ANALYSIS_ENABLED`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_ENDPOINT_URL` 和 `LLM_PROVIDER`。仓库提供 ModelScope 的 OpenAI 兼容接口示例，代码也支持 Anthropic 请求格式。

LLM 调用包含缓存、批量处理、重试和预算控制。缺少密钥、请求失败或预算耗尽时，回退到规则分析。预算采用内部估算，不等于服务商账单；外部调用由用户自己的账户承担。

## 技术栈与开发

- API：FastAPI、SQLAlchemy、Alembic、PostgreSQL。
- 异步任务：Celery、Redis。
- Web：Next.js、React、TypeScript。
- 研究：规则策略、scikit-learn 模型接口、Optuna、可选概率校准。
- 监控：Flower、Prometheus、Grafana。

在项目 Python 环境中运行 API 测试，需要独立的 PostgreSQL 数据库及正确的 `DATABASE_URL`。测试会创建和清理自己的 schema。

```powershell
python -m pytest apps/api/tests/ -q -p no:cacheprovider
npm ci --prefix apps/web
npm --prefix apps/web run test
npm --prefix apps/web run build
```

## 文档

- [启动、配置与首次登录](docs/startup_guide.md)
- [架构概览](docs/architecture/01_overview.md)与[模块说明](docs/architecture/02_modules.md)
- [数据库设计](docs/architecture/03_database.md)与[REST API](docs/architecture/04_api.md)
- [风险与工程约束](docs/architecture/05_tasks_risk.md)
- [当前状态与研究限制](docs/production_upgrade_status.md)
- [开源发布验证](docs/release_verification.md)
- [贡献指南](CONTRIBUTING.md)

高级操作手册位于 `docs/operations/`，描述需要单独选择启用的流程，不属于默认启动步骤。

## 许可证

项目代码使用 [MIT](LICENSE) 许可证。第三方依赖保留各自许可；新闻、行情和外部模型服务按其提供方的条款使用。本项目不提供可再分发的实时行情或新闻全文数据包。
