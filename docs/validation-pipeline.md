# ORCA Validation Pipeline

| Stage | When | Time | Folders Read | Folders Written | What Validated | ORCA Role | User Role |
|---|---|---|---|---|---|---|---|
| **1. Pre-commit** | `git commit` hook | < 2s | `specs/` `candidate/` `templates/` | — | YAML schema · referential integrity · syntax | Idle | Editing specs/configs, committing |
| **2. CI / PR** | PR → `main` | ~30s | `specs/` `candidate/` `tests/` | `diff/` as PR artifact | Full 6-layer · CSPF · Mission 1 & 2 · unit tests | Idle | Reviewing PR, reading diff, approving merge |
| **3. Pre-deploy** | Operator clicks Approve | ~5s | `candidate/` + live gNMI | — | Constraint · digital twin · policy | Runs CSPF + simulation + policy check | Watching dashboard, waiting for green |
| **4. Post-deploy** | After NETCONF commit | ~3s | Live gNMI telemetry | `running/` or `rollback/` | Mission 1 · LSPs stable · utilization | Polls telemetry, commits or rolls back | Notified only if rollback triggered |
| **5. Drift** | Every 5 min | < 1s | `running/` + live get-config | — | Device config matches Git `running/` | Polls devices, diffs against Git | Notified only if drift detected |

## Handoff Point

User owns stages 1–2 (before merge). ORCA owns stages 3–5 (live network).

## Folder Roles

```
specs/       READ  stages 1,2      intent — never written by pipeline
templates/   READ  stage 1         config fragments
candidate/   READ  stages 1,2,3    staged changes awaiting deploy
diff/        WRITE stage 2         auto-generated audit trail
running/     WRITE stage 4 ✅      confirmed live config
rollback/    WRITE stage 4 ❌      checkpoint for discard-changes
```

## NETCONF Mapping (RFC 6241)

| Stage | Operation |
|---|---|
| 3 Pre-deploy | `validate` source=candidate |
| 4 Success | `commit` candidate → running |
| 4 Failure | `discard-changes` → rollback |
| 5 Drift | `get-config` source=running |
