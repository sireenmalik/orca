# Running Configs (NETCONF Running Datastore)

Last confirmed config actually running on each device.

Equivalent to the NETCONF **running datastore** (RFC 6241 §7.5).

## Rules
- Updated ONLY after successful NETCONF commit + telemetry verification
- Never edited manually — written only by the deployment pipeline
- Diff against `candidate/` to see what would change on next push
- Each file tagged with deployment timestamp and Git commit hash

## Rollback
```bash
python -m config_mgmt.push --device R1 --rollback
# Restores running/ checkpoint via NETCONF discard-changes
```
