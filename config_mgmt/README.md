# ORCA Config Management

Workflow sequence — each directory maps to a NETCONF datastore or pipeline stage:

```
specs/                  1. INTENT       — what the network should do (YAML source of truth)
config_mgmt/
  templates/            2. TEMPLATES    — parameterised Nokia/Cisco/Juniper config fragments
  candidate/            3. CANDIDATE    — staged config changes (NETCONF candidate datastore)
  diff/                 4. DIFF         — delta: candidate vs running (pre-push validation)
  running/              5. RUNNING      — last confirmed config on device (NETCONF running datastore)
  rollback/             6. ROLLBACK     — saved checkpoints for instant revert
```

## NETCONF Datastore Mapping (RFC 6241)

| Directory | NETCONF Operation | Description |
|---|---|---|
| `candidate/` | `edit-config` target=candidate | Proposed changes, not yet committed |
| `diff/` | `validate` source=candidate | Pre-commit validation and audit |
| `running/` | `commit` copies candidate→running | What is actually running on the device |
| `rollback/` | `discard-changes` | Revert to last known good |

## Full Workflow

```
specs/ (intent)
    ↓  config_mgmt/renderers/nokia.py
candidate/ (edit-config → candidate datastore)
    ↓  config_mgmt/diff engine
diff/ (validate — 6-layer check)
    ↓  operator approval + git commit
running/ (commit → running datastore via NETCONF)
    ↓  on failure
rollback/ (discard-changes — restore checkpoint)
```

## Git Branching per Stage

```
feature/specs-*     ← spec changes (intent)
cfg/*               ← config changes (candidate → approved)
deploy/*            ← deployment tags (running confirmed)
rollback/*          ← rollback events
```
