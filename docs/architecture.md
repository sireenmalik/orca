# ORCA — Five Macro Processes

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         ORCA Platform                        │
│                                                              │
│  P1: Network Ops      P2: Config Mgmt     P3: Learning       │
│  (seconds)            (minutes-hours)     (days-weeks)       │
│       ↓                     ↓                  ↓            │
│  P4: Digital Twin ────feeds into P1, P2, P3                  │
│  P5: Capacity Planning ─── feeds into P3 future skills       │
└─────────────────────────────────────────────────────────────┘
```

---

## Process 1 — Network Operations & Response
**Time scale: seconds | Runs: continuously | Human involvement: notification only**

The real-time autonomous loop. ORCA watches the network, detects faults,
reroutes LSPs, verifies outcomes, and communicates.

```
Perceive  →  gNMI telemetry every 15s from all devices
Detect    →  threshold breach / link down / alarm
Diagnose  →  CSPF computes candidates + ORCA selects best
Act       →  reroute_lsp / set_link_metric
Verify    →  telemetry confirms Mission 1 & Mission 2
Communicate → email / Teams / TAC case
Write     →  episode committed to skills/past/episodes/
↺ back to Perceive
```

**Guardrails applied:** persistent (hard stops) → past (learned caution) → specs (LSP policy)

**Git role:** reads specs/ and skills/ at startup. Writes episodes after every cycle.

---

## Process 2 — Configuration Management
**Time scale: minutes to hours | Runs: on demand | Human involvement: PR review**

The change management loop. Config changes flow from intent through
validation to production devices via NETCONF.

```
specs/          →  Intent defined (YAML source of truth)
templates/      →  Parameterised config fragments
candidate/      →  Config generated and staged (NETCONF candidate datastore)
diff/           →  Delta computed and posted as PR artifact
PR review       →  Engineer approves merge
running/        →  Committed to device via NETCONF (running datastore)
rollback/       →  Checkpoint saved — instant revert if verification fails
```

**Validation pipeline:**
- Stage 1: pre-commit hook (< 2s) — syntax + schema
- Stage 2: CI on PR (~30s) — full 6-layer + CSPF + unit tests
- Stage 3: pre-deploy (~5s) — constraint + digital twin + policy
- Stage 4: post-deploy (~3s) — telemetry verification
- Stage 5: drift detection (every 5min) — running vs Git

**Git role:** everything. Specs in, configs out, PRs for review, tags for deployments.

---

## Process 3 — Learning & Skill Management
**Time scale: days to weeks | Runs: after every P1 cycle | Human involvement: PR review**

The improvement loop. Every action feeds back into skills,
making ORCA progressively more accurate and deterministic.

```
P1 action completes
    ↓
write_episode → skills/past/episodes/YYYY-MM/ep-{id}.yaml
git commit + push (direct to main for episodes)
    ↓
Patterns emerge across episodes
    ↓
Skill update proposed → PR to skills/past/SKILL.md
Engineer reviews: correct or reject
    ↓
Merged → ORCA git pull on next startup
    ↓
Acts better — more deterministic, better path choices
```

**Hierarchy (immutable rule):**
- Persistent layer: can only be changed by human PR with code review
- Past layer: ORCA writes episodes, engineer promotes to constraints
- Future layer: updated nightly by planning cycle

**Git role:** episode commits are the memory. Skill PRs are the learning gate.

---

## Process 4 — Digital Twin
**Time scale: minutes | Runs: before P2 pre-deploy + nightly | Human involvement: none**
**Status: architecture defined, not yet built**

Mirrors the live network state. Tests proposed changes before they
touch production. Feeds into P2 (Stage 3 pre-deploy validation)
and P3 (future skill scenario planning).

```
Live gNMI telemetry → Digital twin state sync (every 60s)
    ↓
P2 pre-deploy: apply candidate config to twin
    ↓
Simulate traffic for 60s — does Mission 1 hold?
    ↓
Simulate worst-case failure — does the network recover?
    ↓
Pass → P2 proceeds to NETCONF push
Fail → P2 blocked, config returned to candidate/
    ↓
Nightly: run all P3 future skill scenarios against twin
Update projected_utilization in scenario plans
```

**Git role:** reads candidate/ for simulation input. Writes simulation results to diff/ as annotations.

---

## Process 5 — Capacity Planning
**Time scale: weekly | Runs: Sunday 01:00 UTC | Human involvement: review projections**
**Status: architecture defined, not yet built**

Weekly analysis of traffic trends. Generates future specs and
pre-computed reroute plans. Prevents Mission 1 breaches before they happen.

```
Traffic trend analysis (last 30 days of episodes)
    ↓
Project: which links breach 90% in 30 / 60 / 90 days?
    ↓
Generate: new LSP specs / metric adjustments / link additions
    ↓
Validate against persistent rules
    ↓
Commit to skills/future/ as pre-computed scenarios
    ↓
PR opened for engineer review (capacity plan)
    ↓
Approved → merged → ORCA uses pre-computed plans in P1
```

**Git role:** writes to skills/future/ with dated scenario plans. Opens capacity PRs weekly.

---

## How the Five Processes Connect

```
                    ┌─────────────────────────────────┐
                    │         Live Network              │
                    │    gNMI telemetry (15s)          │
                    └──────────┬──────────────┬────────┘
                               │              │
                    ┌──────────▼──────┐   ┌───▼──────────────┐
                    │  P1: Operations │   │  P4: Digital Twin │
                    │  (seconds)      │   │  (minutes)        │
                    └──────┬──────────┘   └────────┬──────────┘
                           │                       │
          episodes         │         validates     │  scenarios
                    ┌──────▼──────┐        ┌───────▼──────────┐
                    │  P3: Learn  │        │  P2: Config Mgmt  │
                    │  (days)     │        │  (hours)          │
                    └──────┬──────┘        └───────────────────┘
                           │
          future skills    │
                    ┌──────▼──────┐
                    │  P5: Capacity│
                    │  (weekly)   │
                    └─────────────┘
```

## Git as the Nervous System

| Process | Reads from Git | Writes to Git |
|---|---|---|
| P1 Operations | specs/, skills/ | skills/past/episodes/ |
| P2 Config Mgmt | specs/, candidate/ | candidate/, diff/, running/, rollback/ |
| P3 Learning | skills/past/episodes/ | skills/past/SKILL.md (via PR) |
| P4 Digital Twin | candidate/ | diff/ (annotations) |
| P5 Capacity | skills/past/episodes/ | skills/future/ (via PR) |
