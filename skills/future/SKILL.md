---
name: orca-future
layer: future
description: >
  Scenario planning, what-if analysis, and pre-computed response plans.
  ORCA uses future skills to prepare responses before faults occur,
  test configs against the digital twin, and plan capacity changes.
  Updated by scheduled planning cycles and operator-initiated scenarios.
---

# ORCA Future Skills

## What Gets Stored

Pre-computed scenarios and response plans:

```yaml
scenario:
  id: "scenario-r1r4-failure"
  name: "R1-R4 Link Failure"
  created: "2026-03-13T00:00:00Z"
  network: "nokia-lab-sfo2"
  type: "failure"                    # failure | congestion | maintenance | capacity
  
  hypothesis:
    link_down: "R1-R4"
    traffic_matrix: "peak_hour"      # baseline | peak_hour | custom
    
  pre_computed_response:
    algorithm: "CSPF"
    optimal_rerouting:
      lsp-customer-a:
        new_path: ["R1","R6","R5","R4"]
        projected_utilization:
          R1-R6: 58.0
          R6-R5: 61.0
          R5-R4: 54.0
      lsp-customer-b:
        new_path: ["R2","R5","R6"]
        projected_utilization:
          R2-R5: 52.0
          R5-R6: 48.0
    mission_1_satisfied: true
    projected_max_utilization: 61.0

  configs_generated:
    - device: "R1"
      vendor: "nokia"
      config_file: "scenarios/r1r4-failure/R1.conf"
      validated: true
    - device: "R2"
      vendor: "nokia"  
      config_file: "scenarios/r1r4-failure/R2.conf"
      validated: true

  twin_test:
    run_at: "2026-03-12T23:00:00Z"
    result: "passed"
    notes: "All links below 65% under peak traffic matrix"

  ready_to_push: true
  approval_required: true
  approved_by: null
```

---

## Scenario Types

### Failure Scenarios
Pre-compute optimal response for every single link failure and common multi-link failures.
Run weekly against the digital twin to keep plans current.

### Congestion Scenarios  
Model traffic growth at 10%, 25%, 50% above baseline.
Identify which links breach Mission 1 first and pre-plan mitigations.

### Maintenance Scenarios
For every planned maintenance window:
- Pre-drain config (increment metrics, reroute LSPs)
- Post-maintenance restore config
- Rollback config if maintenance fails

### Capacity Planning
6-month and 12-month traffic projections.
Identify required new links, new LSPs, metric adjustments.
Generate target configs for planned capacity additions.

---

## Planning Cycle

```
Nightly (02:00 UTC):
  - Run CSPF for all single-link failure scenarios
  - Update pre-computed response plans
  - Validate configs against current topology
  - Flag any scenarios where no feasible solution exists

Weekly (Sunday 01:00 UTC):
  - Full digital twin simulation of all scenarios
  - Capacity trend analysis
  - Update 6-month projections
  - Generate maintenance window configs for upcoming week
```

---

## Integration with Real-Time Response

When a fault occurs, ORCA checks future skills first:
```
1. Does a pre-computed plan exist for this fault?
2. Is the plan still valid? (topology unchanged since last run)
3. If yes → execute pre-computed plan (near-instant response)
4. If no  → compute fresh via CSPF + reasoning
```

This reduces response time from 15-30 seconds to 2-3 seconds for anticipated faults.
