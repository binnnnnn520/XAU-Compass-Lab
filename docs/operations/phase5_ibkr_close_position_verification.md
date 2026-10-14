# Phase 5 IBKR Paper Close-Position Verification

This runbook governs the one-time supervised IBKR paper close-position evidence run. It is separate from the 14-day gray-release observation window.

Remote server entrypoint, when the verification is performed on the server:

```powershell
ssh research-host
```

## 1. Scope

The goal is to produce real IBKR paper runtime evidence that the guarded close-position path can close a small paper position after all Phase 5 manual approval, readiness, routing, credential, health-check, and account snapshot gates pass.

This run must remain paper-only. It must not enable strategy-driven live routing and must not leave `PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=true` after the one-time verification command finishes.

## 2. Required Operator Approval Metadata

Use command-local values for the supervised run:

```text
PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED=true
IBKR_PAPER_CLOSE_EXISTING_POSITION=true
IBKR_PAPER_ORDER_TYPE=market
IBKR_PAPER_CANCEL_AFTER_SUBMIT=false
IBKR_PAPER_MANUAL_APPROVAL_ID=<approval-id>
IBKR_PAPER_MANUAL_APPROVAL_ACTOR=<operator>
IBKR_PAPER_MANUAL_APPROVED_AT=<UTC datetime>
```

`IBKR_PAPER_MANUAL_APPROVED_AT` must be UTC-aware, for example `2026-05-19T00:00:00+00:00`.

## 3. Pre-Checks

Before creating or closing any paper position:

```powershell
Get-ChildItem Env:IBKR_PAPER_SANDBOX_* | Select-Object -ExpandProperty Name
Test-NetConnection -ComputerName $env:IBKR_PAPER_SANDBOX_HOST -Port ([int]$env:IBKR_PAPER_SANDBOX_PORT) -InformationLevel Quiet
```

Then use the IBKR paper client to run:

```text
reqOpenOrders()
reqPositions()
```

Record the open-order list and the target symbol position state before the close-position run.

## 4. Position Requirement

The runtime verification path only submits a close order when it can observe a matching open paper position for the target symbol.

If no matching position exists, the operator may create one tiny paper position manually in the IBKR paper account, then rerun `reqPositions()` to prove that the position is available for the close-position evidence run.

Use the smallest practical notional. Do not create a position in a live account.

The runtime verifier polls briefly for the target paper position before submitting the close order. The default limits are:

```text
IBKR_PAPER_POSITION_CONFIRMATION_ATTEMPTS=3
IBKR_PAPER_POSITION_CONFIRMATION_SLEEP_SECONDS=1.0000
```

Keep these values small. They exist only to handle normal IBKR paper position-sync delay after a tiny supervised entry order.

## 5. Verification Command

Run from the repository root:

```powershell
$env:PYTHONPATH='apps/api'
$env:PHASE5_IBKR_PAPER_ORDER_EXECUTION_ENABLED='true'
$env:IBKR_PAPER_CLOSE_EXISTING_POSITION='true'
$env:IBKR_PAPER_ORDER_TYPE='market'
$env:IBKR_PAPER_CANCEL_AFTER_SUBMIT='false'
$env:IBKR_PAPER_POSITION_CONFIRMATION_ATTEMPTS='3'
$env:IBKR_PAPER_POSITION_CONFIRMATION_SLEEP_SECONDS='1.0000'
$env:IBKR_PAPER_MANUAL_APPROVAL_ID='phase5-close-position-verify'
$env:IBKR_PAPER_MANUAL_APPROVAL_ACTOR='phase5_admin'
$env:IBKR_PAPER_MANUAL_APPROVED_AT='<UTC datetime>'
D:\APP\anaconda\envs\gold-agent\python.exe -m app.services.broker.ibkr_paper_runtime_verification
```

Expected success evidence:

```text
accepted=true
status='closed'
close_order_id=<non-null id>
lifecycle includes close_submitted
account_id=redacted
```

If the command returns `close_skipped_no_position`, the close-position evidence is not complete.

## 6. Post-Checks

After the verification command completes, use the IBKR paper client to run:

```text
reqOpenOrders()
reqPositions()
```

Required post-run state:

- no residual API open orders for the verification run
- no residual target paper position that should have been closed
- no account IDs, secrets, passwords, or tokens written to repository files

## 7. Status Ledger Update

Record the redacted JSON evidence, pre-check result, post-check result, and final decision in `docs/production_upgrade_status.md`.

If the external IBKR paper environment is missing or unreachable, record the concrete blocker instead of marking close-position evidence complete.
