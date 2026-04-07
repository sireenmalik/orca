---
name: orca-past
layer: past
authority: medium — can tighten persistent constraints, never loosen them
description: >
  Episodic memory and learned constraints from operational history.
  Past skill adds network-specific caution on top of persistent rules.
  It can make ORCA MORE conservative but never LESS conservative.
---

# ORCA Past Skills — Guardrail Layer 2

## Authority Rule

Past skills can TIGHTEN constraints from the persistent layer.
Past skills can NEVER LOOSEN persistent layer constraints.

Examples:
- ✅ "Avoid R5-R6 — it flapped 3 times this month" (tightening scope)
- ✅ "Treat R3-R4 utilization threshold as 80% not 90% — historically unreliable" (tightening Mission 1)
- ❌ "R1-R4 has been stable, ignore the 90% threshold" (loosening — BLOCKED)
- ❌ "Skip verification — this reroute always works" (loosening — BLOCKED)

---

## What Gets Stored

Every action cycle writes a structured episode:

```yaml
episode:
  id: "ep-20260413-001"
  timestamp: "2026-04-13T14:23:00Z"
  network: "nokia-lab-sfo2"

  trigger:
    type: "link_failure"
    link: "R1-R4"

  decision:
    algorithm: "CSPF"
    path_used: ["R1","R6","R5","R4"]
    reasoning: "Pre-computed plan from future skill. Mission 1 confirmed."

  outcome:
    success: true
    time_to_resolution_seconds: 12
    mission_1_satisfied: true
    mission_2_improvement: 32.7
    human_override: false
    post_action_stability_minutes: 240

  learned_constraints:
    # Populated when outcomes reveal patterns
    # e.g. if this path fails repeatedly:
    # avoid_path: ["R1","R6","R5","R4"]
    # reason: "Three failures in 7 days — possible optics issue on R5-R6"
```

---

## Learned Constraint Types

```yaml
learned_constraints:

  link_caution:
    # Links with recent instability — treated more conservatively
    # Auto-populated from flap history
    # Example:
    # - link: "R5-R6"
    #   adjusted_threshold_pct: 80    # tighter than persistent 90%
    #   reason: "Flapped twice in last 30 days"
    #   expires: "2026-05-13"

  path_avoidance:
    # Paths that caused instability — avoided unless no alternative
    # Example:
    # - path: ["R1","R6","R5","R4"]
    #   reason: "Caused micro-congestion on R5-R6 under peak load"
    #   confidence: 0.8

  override_patterns:
    # Operator overrides — ORCA learns from human corrections
    # Example:
    # - action: reroute_lsp
    #   lsp: "lsp-customer-a"
    #   orca_proposed: ["R1","R6","R5","R4"]
    #   operator_chose: ["R1","R4"]
    #   reason: "R6 scheduled for maintenance"
    #   learned: "prefer direct path during evening hours"
```

---

## How ORCA Uses Past Skills

At analysis time, past skills are injected into context:

```
LEARNED CONSTRAINTS (active):
  None currently active

RECENT HISTORY (last 5 similar incidents):
  2026-04-10: R1-R4 failure — R1→R6→R5→R4 used — stable 4h — no override
  2026-04-08: R2-R3 congestion — R2→R5→R6 used — stable 2h — no override
  2026-04-05: R1-R4 failure — R1→R6→R5→R4 used — stable 6h — no override
```

ORCA reads this before deciding. Three successful uses of the same path
increases confidence. An operator override adds a learned constraint.
