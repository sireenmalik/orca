# Config Diffs (Pre-Commit Validation)

Diffs generated between `candidate/` and `running/` before every push.

Retained indefinitely — full audit trail of every network change.

## Naming: {network}-{device}-{YYYYMMDD}-{HHMM}.diff
## Format: unified diff (+added, -removed, unchanged)

## Each diff header contains
- Source spec Git commit hash
- Operator who approved
- Validation results (6-layer)
- Deployment timestamp
- Outcome: committed | rolled-back
