---
name: orca-past
layer: past
description: >
  Episodic memory — learned from historical actions and outcomes.
  Loaded into ORCA context at analysis time to inform decisions.
  Updated after every action cycle with outcome data.
  Grows richer with every deployment.
---

# ORCA Past Skills

## What Gets Stored

Every action cycle writes a structured record:

```yaml
episode:
  id: "ep-20260313-001"
  timestamp: "2026-03-13T01:35:00Z"
  network: "nokia-lab-sfo2"
  
  trigger:
    type: "link_failure"           # link_failure | congestion | manual | scheduled
    link: "R1-R4"
    utilization_before: 0.0
    state_before: "down"
    
  context:
    affected_lsps: ["lsp-customer-a", "lsp-customer-b"]
    congested_links:
      R1-R2: 94.5
      R3-R4: 89.5
    active_alarms: 1

  decision:
    algorithm: "CSPF"
    reasoning_summary: "R1-R4 down. Rerouted customer-a via R1-R6-R5-R4, customer-b via R2-R5-R6"
    actions_taken:
      - type: reroute_lsp
        lsp: "lsp-customer-a"
        old_path: ["R1","R2","R3","R4"]
        new_path: ["R1","R6","R5","R4"]
      - type: reroute_lsp
        lsp: "lsp-customer-b"
        old_path: ["R2","R3","R4","R5","R6"]
        new_path: ["R2","R5","R6"]

  outcome:
    success: true
    time_to_resolution_seconds: 47
    utilization_after:
      R1-R2: 61.8
      R3-R4: 47.0
    mission_1_satisfied: true
    mission_2_improvement: 32.7
    human_override: false
    override_reason: null

  notifications:
    ops_notified: true
    tac_case_opened: true
    tac_vendor: "nokia"
    tac_priority: "P1"
```

---

## How ORCA Uses Past Episodes

At analysis time, ORCA loads the 10 most recent relevant episodes and extracts:

- Which paths performed well on this topology
- Which actions caused unintended side effects
- How long similar resolutions took
- Whether human overrides occurred and why
- Patterns that preceded larger failures

This is injected into the context as:
```
RECENT HISTORY (last 10 similar incidents):
- 2026-03-12: R2-R3 congestion resolved via R2-R5-R6 reroute. Mission 2 improved 28%. No override.
- 2026-03-10: R1-R4 failure. R1-R6-R5-R4 path used. Stable for 4 hours.
- 2026-03-08: R3-R4 congestion. Human override — operator noted R5-R6 link has intermittent errors.
```

---

## Loader

```python
# memory/episodic/loader.py
def load_relevant_episodes(trigger_type: str, affected_links: list, n: int = 10) -> list:
    """Load most recent relevant episodes for context injection."""
    ...

def write_episode(episode: dict) -> str:
    """Write episode to persistent store. Returns episode ID."""
    ...
```

---

## Storage

- Format: YAML files per episode + PostgreSQL index for fast retrieval
- Location: `memory/episodic/episodes/YYYY-MM/ep-{id}.yaml`
- Index: episodes.db — searchable by trigger_type, link, lsp, outcome
- Retention: indefinite — this is the system's operational knowledge base
