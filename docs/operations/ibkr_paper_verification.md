# IBKR Paper Close-Position Verification / IBKR 模拟平仓检查

This optional, supervised procedure verifies that the guarded paper-account close path can close an existing small position. It can send an order to your IBKR paper account. It must not connect to a live account or enable strategy-driven broker routing.

本流程会向自行配置的 IBKR 模拟账户发送平仓指令，不是只读检查。请先确认账户类型、目标持仓和人工授权，勿使用真实资金账户。

## 1. Prerequisites

- A reachable IBKR Gateway/TWS paper session, configured using local environment variables.
- A healthy account snapshot and satisfied readiness, routing, credential, risk, and manual-approval guards.
- A matching open paper position for the target symbol.
- An operator available to inspect open orders and positions before and after execution.

Use the smallest practical notional. If there is no matching position, this check cannot verify a close. Creating a test position is a separate, deliberate paper-account action.

See [broker safety](broker_safety.md) before proceeding.

## 2. Pre-checks

Check connectivity without printing credential values:

```powershell
Get-ChildItem Env:IBKR_PAPER_SANDBOX_* | Select-Object -ExpandProperty Name
Test-NetConnection -ComputerName $env:IBKR_PAPER_SANDBOX_HOST -Port ([int]$env:IBKR_PAPER_SANDBOX_PORT) -InformationLevel Quiet
```

Use the paper client to inspect:

```text
reqOpenOrders()
reqPositions()
```

Record the target symbol, position size, and open-order state privately. Do not proceed with unexpected or conflicting orders.

## 3. Required command-local settings

```dotenv
PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=true
IBKR_PAPER_CLOSE_EXISTING_POSITION=true
IBKR_PAPER_ORDER_TYPE=market
IBKR_PAPER_CANCEL_AFTER_SUBMIT=false
IBKR_PAPER_MANUAL_APPROVAL_ID=<approval-id>
IBKR_PAPER_MANUAL_APPROVAL_ACTOR=<operator>
IBKR_PAPER_MANUAL_APPROVED_AT=<UTC datetime>
```

The verifier briefly polls for position synchronization. Defaults are `IBKR_PAPER_POSITION_CONFIRMATION_ATTEMPTS=3` and `IBKR_PAPER_POSITION_CONFIRMATION_SLEEP_SECONDS=1.0000`. Keep retries bounded.

## 4. Execute under supervision

Run from the repository root in the project's Python environment. Supply approval metadata for this action only:

```powershell
$env:PYTHONPATH='apps/api'
$env:PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED='true'
$env:IBKR_PAPER_CLOSE_EXISTING_POSITION='true'
$env:IBKR_PAPER_ORDER_TYPE='market'
$env:IBKR_PAPER_CANCEL_AFTER_SUBMIT='false'
$env:IBKR_PAPER_MANUAL_APPROVAL_ID=Read-Host 'Approval ID'
$env:IBKR_PAPER_MANUAL_APPROVAL_ACTOR=Read-Host 'Operator'
$env:IBKR_PAPER_MANUAL_APPROVED_AT=[DateTime]::UtcNow.ToString('o')
try {
    python -m app.services.broker.ibkr_paper_runtime_verification
} finally {
    $env:PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED='false'
    Remove-Item Env:\IBKR_PAPER_CLOSE_EXISTING_POSITION -ErrorAction SilentlyContinue
    Remove-Item Env:\IBKR_PAPER_ORDER_TYPE -ErrorAction SilentlyContinue
    Remove-Item Env:\IBKR_PAPER_CANCEL_AFTER_SUBMIT -ErrorAction SilentlyContinue
    Remove-Item Env:\IBKR_PAPER_MANUAL_APPROVAL_ID -ErrorAction SilentlyContinue
    Remove-Item Env:\IBKR_PAPER_MANUAL_APPROVAL_ACTOR -ErrorAction SilentlyContinue
    Remove-Item Env:\IBKR_PAPER_MANUAL_APPROVED_AT -ErrorAction SilentlyContinue
}
```

Expected successful output includes:

```text
accepted=true
status='closed'
close_order_id=<non-null id>
lifecycle includes close_submitted
account_id=redacted
```

`close_skipped_no_position` is not a verified close. A failed command or an unavailable external service is not a successful verification.

## 5. Post-checks and cleanup

Run `reqOpenOrders()` and `reqPositions()` again. Confirm no residual orders from this check and no target position that should have been closed. Investigate unexpected state before further actions; an API return value alone does not replace broker-side inspection.

Keep a redacted result, pre/post-checks, UTC timestamps, and any failure details in your private experiment record. Do not commit account IDs, credentials, or raw account exports. Confirm paper execution remains disabled in every runtime process; the command-local flag does not need to be enabled in Compose.
