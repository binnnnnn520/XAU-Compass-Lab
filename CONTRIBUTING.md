# Contributing / 贡献指南

Use the [Chinese README](README.md) or [English README](README.en.md) to set up an isolated development environment. Follow the [development guidelines](docs/development.md) for engineering contracts and review expectations.

- Describe the problem, expected behavior, and a minimal reproduction in issues.
- Keep changes focused and include relevant test evidence.
- Preserve UTC timestamps, Decimal finance values, strict feature-time filtering, append-only audit logs, and shared signal entry points.
- Keep both READMEs and relevant REST documentation consistent.
- Never include provider keys, passwords, personal runtime exports, or `.env` files in a pull request.
- Keep broker execution and observation collection disabled during routine development and automated tests; use mocks for external accounts.

API tests use pytest and an isolated PostgreSQL schema. Web checks use the existing `test` and `build` npm scripts. See the [testing guide](docs/testing.md) for commands.

请提交范围明确的修改，并说明复现方式、预期行为及实际验证结果。代码与文档遵循现有工程约束；凭据和个人运行数据不得进入提交。
