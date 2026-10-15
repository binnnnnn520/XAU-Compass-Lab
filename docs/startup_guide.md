# Startup Guide / 启动指南

Run an isolated local research and paper-trading environment. Broker submission and optional observation collection stay disabled.

本指南用于本地研究与模拟交易，默认不启用券商下单及可选观测采集。以下命令从仓库根目录运行。

## 1. Requirements / 环境要求

- Docker with a running Linux engine and Docker Compose.
- For development outside Docker: Python 3.13+, Node.js 22, and npm.
- Use a project virtual environment. Local Python tests must not use an unrelated environment.

Windows users should start Docker Desktop before invoking Compose. PowerShell can use `npm.cmd` if script execution policy blocks `npm.ps1`.

## 2. Local configuration / 本地配置

```powershell
Copy-Item .env.example .env
```

Replace `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, and `AUTH_TOKEN_SECRET` with locally generated values. Update the password portions of `DATABASE_URL` and `REDIS_URL` to match. For simple URL construction, use random hexadecimal values rather than characters that require URL encoding.

将以上四个占位值替换为自己的随机值，并同步修改两个连接 URL。可用项目 Python 为每个值分别生成随机十六进制字符串：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Compose validates Grafana's required variables even when you only start the core services, so its password must also be configured. Local `.env` files and backups are ignored by Git and Docker.

默认保持这些设置：

```dotenv
LLM_ANALYSIS_ENABLED=false
PHASE5_OBSERVATION_COLLECTION_ENABLED=false
PHASE5_EVIDENCE_WINDOW_STARTED=false
PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=false
IBKR_PAPER_SANDBOX_MODE=paper
```

## 3. Build and migrate / 构建与迁移

```powershell
docker compose build api web
docker compose up -d postgres redis
docker compose run --rm api python -m alembic upgrade head
```

The API migration command runs from the API image's configured working directory. Existing Alembic migrations define the schema; do not replace them with ad-hoc table creation.

## 4. First administrator / 初始化首个管理员

The application does not ship a shared default login. Call only the `ensure_admin` helper below; the module's command-line entry point also adjusts strategy parameters and is not needed for account creation.

项目不提供默认公共密码。下面仅调用已有管理员初始化函数，不运行策略调参、不启用额外采集、不发送券商订单。

```powershell
$env:PHASE5_ADMIN_USERNAME = Read-Host "Administrator username"
$adminPassword = Read-Host "Administrator password" -AsSecureString
$env:PHASE5_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $adminPassword).Password
@'
from app.database import SessionLocal
from scripts.phase5_soak_setup import ensure_admin

with SessionLocal.begin() as session:
    ensure_admin(session)
'@ | docker compose run --rm -T -e PHASE5_ADMIN_USERNAME -e PHASE5_ADMIN_PASSWORD api python -
Remove-Item Env:\PHASE5_ADMIN_PASSWORD
Remove-Item Env:\PHASE5_ADMIN_USERNAME
```

For Bash, read your values into exported variables and run the same Python through stdin:

```bash
read -r -p 'Administrator username: ' PHASE5_ADMIN_USERNAME
read -r -s -p 'Administrator password: ' PHASE5_ADMIN_PASSWORD
export PHASE5_ADMIN_USERNAME PHASE5_ADMIN_PASSWORD
docker compose run --rm -T -e PHASE5_ADMIN_USERNAME -e PHASE5_ADMIN_PASSWORD api python - <<'PY'
from app.database import SessionLocal
from scripts.phase5_soak_setup import ensure_admin

with SessionLocal.begin() as session:
    ensure_admin(session)
PY
unset PHASE5_ADMIN_USERNAME PHASE5_ADMIN_PASSWORD
```

Re-running the helper preserves an existing user's password. It grants the admin role if missing; use it only for the intended local administrator account.

## 5. Start and inspect / 启动与检查

```powershell
docker compose up -d api worker beat web flower
Invoke-RestMethod http://localhost:8000/api/v1/health
```

| Surface | Default URL |
| --- | --- |
| Web UI / 前端 | http://localhost:3000 |
| API health | http://localhost:8000/api/v1/health |
| OpenAPI | http://localhost:8000/docs |
| Flower | http://localhost:5555 |

Open the Web UI and sign in with the account you created. API clients use `POST /api/v1/auth/login` with `username` and `password`, then pass the returned access token as a Bearer token. Admin-only registration creates additional local users; public registration is not enabled.

登录后可依次查看 Dashboard、News、Signals、Backtests、Paper Trading 和 Risk Ops。外部数据源的可用性、更新频率和访问条款由相应提供方决定。来源失败时应查看状态与日志，不应填入伪造行情。

Optional monitoring:

```powershell
docker compose up -d prometheus grafana
```

Grafana defaults to http://localhost:3001 and Prometheus to http://localhost:9090.

## 6. Optional LLM / 可选 LLM

Set `LLM_ANALYSIS_ENABLED=true`, supply your own `LLM_API_KEY`, and select a model, endpoint, and provider. `LLM_PROVIDER=openai` selects OpenAI-compatible formatting; the example endpoint is ModelScope rather than OpenAI itself. Use `anthropic` with the corresponding endpoint when selecting Anthropic formatting.

Restart the relevant services after changing configuration:

```powershell
docker compose up -d --force-recreate api worker beat
```

Only enable LLM analysis when you intend to use your provider account. Cache hits do not require a new request. Failures and the internally estimated daily budget trigger rule-based fallback; verify provider billing separately.

## 7. Development and tests / 开发与测试

Use a dedicated PostgreSQL database for tests. Host-side connections use `127.0.0.1`; Compose services use `postgres` and `redis` as hostnames. The test suite creates and cleans an isolated schema.

```powershell
python -m pip install -e apps/api
python -m pip install pytest
python -m pytest apps/api/tests/ -q -p no:cacheprovider
npm ci --prefix apps/web
npm --prefix apps/web run test
npm --prefix apps/web run build
```

Never point tests at a shared runtime database. The CI workflow supplies disposable services and also verifies clean Compose startup and login.

## 8. Logs, shutdown, and conflicts / 日志与停止

```powershell
docker compose logs --tail=100 api worker beat
docker compose stop
```

`docker compose down` removes this Compose project's containers and network while keeping named volumes. Deleting volumes removes local research data; routine shutdown does not require it.

Override `WEB_PORT`, `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `FLOWER_PORT`, `PROMETHEUS_PORT`, or `GRAFANA_PORT` in your local configuration when ports conflict. Use a separate Compose project name when running multiple copies, and do not stop another project's containers.

Optional tools: [broker sandbox safety](operations/broker_safety.md), [observation collection](operations/paper_observation.md), [backups](../infra/backup/README.md), and [isolated recovery rehearsal](../infra/dr/README.md). Each requires separate configuration; none is needed for the default research workflow.
