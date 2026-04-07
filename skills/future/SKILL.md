---
name: orca-future
layer: future
authority: lowest — pre-computed suggestions only, always validated against persistent
description: >
  Pre-computed response plans and scenario configs.
  Future skill provides fast answers for anticipated faults.
  Every plan is validated against persistent rules before use.
  Stale or invalid plans are discarded — CSPF recomputes fresh.
---

# ORCA Future Skills — Guardrail Layer 3

## Authority Rule

Future skills provide SUGGESTIONS only.
Every suggestion is validated against persistent layer before execution.
If a pre-computed plan violates any persistent rule — it is DISCARDED.
ORCA never executes a future plan that hasn't passed persistent validation.

```
Future plan exists?
    ↓ yes
Validate against persistent rules (CSPF + Mission 1 check)
    ↓ passes
Check past skill — any learned constraints apply?
    ↓ clear
Execute plan (fast path — no LLM reasoning needed)

Validate against persistent rules
    ↓ FAILS (topology or traffic changed)
Discard plan
    ↓
CSPF recomputes fresh
    ↓
ORCA reasons over new candidates
```

---

## Pre-Computed Scenarios

Updated nightly at 02:00 UTC. Each scenario:

```yaml
scenario:
  id: "r1-r4-failure"
  computed_at: "2026-04-13T02:00:00Z"
  valid_until: "2026-04-14T02:00:00Z"   # expires after 24h — recomputed nightly
  network: "nokia-lab-sfo2"
  trigger: { link_down: "R1-R4" }

  response:
    algorithm: CSPF
    validated_against_persistent: true
    mission_1_confirmed: true
    projected_max_utilization: 61.0

    actions:
      - reroute_lsp:
          lsp: "lsp-customer-a"
          new_path: ["R1","R6","R5","R4"]
          projected_util: { R1-R6: 58.0, R6-R5: 61.0, R5-R4: 54.0 }
      - reroute_lsp:
          lsp: "lsp-customer-b"
          new_path: ["R2","R5","R6"]
          projected_util: { R2-R5: 52.0, R5-R6: 48.0 }

  config_files:
    - config_mgmt/candidate/nokia-lab-sfo2/R1.conf
    - config_mgmt/candidate/nokia-lab-sfo2/R2.conf
```

---

## Planning Cycle

```
Nightly 02:00 UTC:
  For every single-link failure scenario:
    1. Run CSPF with link removed
    2. Validate against persistent rules
    3. Check past skill for learned constraints
    4. Store plan if valid, discard if not
    5. Flag scenarios with no feasible solution → ops alert

Weekly Sunday 01:00 UTC:
  Full digital twin simulation
  Capacity trend analysis
  Maintenance window config generation
```

---

## Expiry and Invalidation

Plans expire after 24 hours or are invalidated immediately if:
- Topology changes (link added/removed)
- Traffic matrix shifts >20% from baseline
- A past skill learned constraint applies to the planned path
- Persistent rule change (requires code review)

Expired or invalid plans are never used — CSPF always recomputes.
