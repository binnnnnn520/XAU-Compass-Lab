# Open-source Release Verification / 开源发布验证

## Baseline

- Source snapshot: `e764e5c9c945c4b539d60c2744664b0f5a23816e`.
- The predecessor repository was pushed and its remote SHA matched before export.
- The new snapshot excludes predecessor Git history, local configuration, internal prompts, and archived packages.
- MIT copyright holder: `binnnnnn520`.
- Commit author: `bin`, using the account's GitHub noreply email.
- Real-money deployment and the 14-day acceptance window remain paused.

## Verification results

| Check | Result |
| --- | --- |
| Chinese and English README consistency | Pending |
| Markdown links and retained runbook dependencies | Pending |
| Environment defaults and auth-secret forwarding | Pending |
| Gitleaks scan, with redacted reporting | Pending |
| Local relevant tests | Pending |
| Complete API regression in CI | Pending |
| Web tests and production build | Pending |
| Clean Compose startup and first administrator login | Pending |
| Fresh Git history and author identity | Pending |

Publication requires these checks to pass. CI uses isolated disposable databases and services; it does not start the formal evidence window or submit broker orders.
