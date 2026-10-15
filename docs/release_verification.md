# Open-source Release Verification / 开源发布验证

## Baseline

- Source snapshot: `e764e5c9c945c4b539d60c2744664b0f5a23816e`.
- The predecessor repository was pushed and its remote SHA matched before export.
- The new snapshot excludes predecessor Git history, local configuration, internal prompts, and archived packages.
- MIT copyright holder: `binnnnnn520`.
- Commit author: `bin`, using the account's GitHub noreply email.
- Real-money deployment and the 14-day acceptance window remain paused.

## Verification results

| Check | Result / live evidence |
| --- | --- |
| Chinese and English README consistency | Both versions and reciprocal language links checked |
| Markdown links and retained runbook dependencies | No missing local link targets; retained runbook tests passed |
| Environment defaults and auth-secret forwarding | Included in 20 passing local configuration/runbook tests |
| Gitleaks scan, with redacted reporting | Gitleaks 8.30.1: zero findings in exported files and initial Git history |
| Local relevant tests | `20 passed`; API source/tests compile successfully |
| Complete API regression in CI | `316 passed, 24 warnings` in the initial run; repaired CI also passed; current release result: API regression job |
| Web tests and production build | Passed in the repaired CI run; current release result: Web regression job |
| Clean Compose startup and first administrator login | Passed in the repaired CI run; current release result: Clean Compose startup job |
| Fresh Git history and author identity | Initial history contains only `bin` with the user's GitHub noreply address; contributor resolves to `binnnnnn520` |

Current CI evidence: [CI workflow runs](https://github.com/binnnnnn520/XAU-Compass-Lab/actions/workflows/ci.yml). Publication requires all three jobs to succeed for the current release commit; this table does not turn an unexecuted or failing CI job into a pass.

The [initial run](https://github.com/binnnnnn520/XAU-Compass-Lab/actions/runs/38567874292) exposed a missing npm lockfile and an uncaught transient connection reset in the new startup check. API regression passed. Release preparation adds the lockfile and corrects the bounded readiness retry; subsequent CI is the verification for those fixes.

The [repaired run](https://github.com/binnnnnn520/XAU-Compass-Lab/actions/runs/38570134505) passed all three jobs and produced the dependency lockfile. The final release commits that lockfile and uses Node.js 22 with `npm ci` in both the Web job and Docker build; all three jobs must pass again on that actual release snapshot before publication.

Migration comparison checked 101 backend Python modules by AST and 40 predecessor-tracked Web files after line-ending normalization: no application behavior changes. Text checkout uses LF for Linux compatibility; predecessor source files with harmless extra blank lines are preserved.

Publication requires these checks to pass. CI uses isolated disposable databases and services; it does not start the formal evidence window or submit broker orders.
