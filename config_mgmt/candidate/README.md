# Candidate Configs (NETCONF Candidate Datastore)

Configs staged for deployment — proposed but not yet committed to devices.

Equivalent to the NETCONF **candidate datastore** (RFC 6241 §7.5).

## Rules
- Generated from `specs/` by `config_mgmt/renderers/`
- Reviewed via diff against `running/`
- Never pushed to a device directly — must pass 6-layer validation first
- Every change here creates a `cfg/*` Git branch for review

## Status Tags (in file header)
- `BASELINE` — generated from specs, never deployed
- `PENDING_REVIEW` — awaiting operator approval
- `APPROVED` — passed validation, ready to commit
