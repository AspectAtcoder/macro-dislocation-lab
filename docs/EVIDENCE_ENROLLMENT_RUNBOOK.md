# Licensed evidence-enrollment runbook

This runbook enrolls operational evidence only. It does not join market prices,
fit a model, generate an order or establish an edge.

## 1. Close the external access gate

Store the provider credential only in `TRADING_ECONOMICS_API_KEY` and keep the
approved attestation under an ignored `data/private/` path. Then run:

```bash
macro-lab vendor-access-preflight \
  --rights-attestation data/private/trading_economics_rights.json
```

The command reports only credential presence, attestation validity and license
class. It never prints the credential. A nonzero exit means no authenticated
capture may start.

## 2. Capture one release window

Follow `docs/SHADOW_CAMPAIGN_RUNBOOK.md`. Preserve:

- the exact BLS schedule bytes and resulting Phase 4 plan;
- the Phase 3 content-addressed capture store;
- the Phase 4 append-only trace store;
- the same run ID and plan ID across all evidence.

The pre-release trace event must reference the HTTPS consensus capture ID. Every
release component must reference the websocket capture ID containing that exact
provider event ID. Do not edit an old trace to repair a failed window.

## 3. Build the cross-linked package

```bash
macro-lab audit-evidence-package \
  --schedule data/raw/schedules/release_schedule.json \
  --trace-store data/raw/shadow/RUN_ID \
  --capture-store data/raw/vendor_capture_store/RUN_ID \
  --plan-id PLAN_ID \
  --rights-attestation data/private/trading_economics_rights.json \
  --output data/raw/evidence/RUN_ID.json
```

Review `structural_issues`, `eligibility_issues`, `enrollable` and `package_hash`.
The audit independently recomputes capture receipt IDs, raw blob hashes, byte
lengths, normalized components and store integrity. `store_audit.passed=true` in
the trace is accepted only when it equals the fresh report.

## 4. Enroll and checkpoint

Only an issue-free package with `enrollable=true` can enter the ledger:

```bash
macro-lab enroll-evidence-package \
  --package data/raw/evidence/RUN_ID.json \
  --ledger data/raw/evidence_ledger

macro-lab campaign-checkpoint \
  --ledger data/raw/evidence_ledger \
  --output data/raw/evidence_ledger/checkpoint.json
```

The append operation locks duplicate checking and writing as one critical section.
Duplicate package, run, plan or release-window identities fail closed. Promotion
requires six distinct packages, including three CPI and three NFP windows.

## 5. Stop boundary

Do not attach prices when the campaign checkpoint becomes promoted. Preserve the
ledger, freeze the eligible package IDs and preregister the separate price trial,
including executable start time, target, features, costs, holdout and trial count.
