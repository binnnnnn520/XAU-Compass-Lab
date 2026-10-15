# Testing and Verification / 测试与验证

Use isolated local services and the existing test suites to check changes. Report commands and actual results rather than inferring success from a previous run.

使用独立环境和现有测试验证修改，记录实际命令与结果。测试数据用于验证软件行为，不代表策略盈利能力。

## API tests / 后端测试

Use Python 3.13+ in a dedicated project environment. Set `DATABASE_URL` to a disposable PostgreSQL database and configure Redis before running the full suite. Tests create and remove their own schema; never use a shared runtime database.

From the repository root:

```powershell
python -m pip install -e apps/api
python -m pip install pytest
python -m compileall apps/api/app apps/api/tests -q
python -m pytest apps/api/tests/ -q -p no:cacheprovider
```

For documentation and configuration changes, a focused check is:

```powershell
python -m pytest apps/api/tests/test_open_source_docs.py apps/api/tests/test_phase5_runbook.py apps/api/tests/test_phase5_gray_release_ops.py apps/api/tests/test_phase5_dr_deployment.py apps/api/tests/test_backup_scripts.py apps/api/tests/test_security_config.py -q -p no:cacheprovider
```

These checks cover documentation links, safe configuration defaults, runbook instructions, and script contracts. They do not start Compose, connect to a broker, or submit orders.

## Web tests / 前端测试

Use Node.js 22 and the committed npm lockfile:

```powershell
npm ci --prefix apps/web
npm --prefix apps/web run test
npm --prefix apps/web run build
```

Do not regenerate dependency versions merely to work around an unrelated test failure.

## CI

[GitHub Actions](https://github.com/binnnnnn520/XAU-Compass-Lab/actions/workflows/ci.yml) runs three independent jobs:

| Job | Checks |
| --- | --- |
| API regression | Source compilation and the complete API test suite with disposable PostgreSQL and Redis |
| Web regression | Locked dependency installation, tests, and a production build |
| Clean Compose startup | Disposable secrets, image builds, database migrations, administrator initialization, health checks, and login |

Check results for the commit being reviewed. A successful older run is not evidence that newer changes pass. CI does not use broker credentials or enable paper-account order submission.

## Documentation and secrets / 文档与敏感信息

- Keep Chinese and English READMEs aligned.
- Keep relative links and documented script paths valid.
- Describe current capabilities, configuration, and limitations without personal development history.
- Do not commit `.env`, credentials, account exports, runtime logs, or downloaded models.
- Review the staged diff and use a secret scanner before publishing changes.
- Redact sensitive values in diagnostics; never copy tokens or account identifiers into public issues.

## Scope of results / 结果边界

A test verifies the behavior it exercises. Mock broker checks do not establish external connectivity; startup checks do not establish provider availability; backtest fixtures do not establish predictive value. Report unavailable services and unexecuted checks explicitly.
