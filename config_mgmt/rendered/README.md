# Rendered Configs

Router configs generated from specs. Not yet deployed.

## Flow
```
specs/ (intent) → rendered/ (proposed) → diff vs deployed/ → deployed/ (live)
```

## Status Tags
- `BASELINE` — generated, never deployed
- `PENDING_REVIEW` — awaiting operator approval
- `APPROVED` — approved, ready to push
- `DEPLOYED` — confirmed on device
- `ROLLED_BACK` — reverted after failure
