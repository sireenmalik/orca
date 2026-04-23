# ORCA — Project Specification
**Autonomous Network Operations & Response Agent**
Version: **1.0.0-baseline** | Last updated: 2026-04-23

Baseline tagged `v1.0.0` on commit — all three use cases (LSP
reroute + approve, security rogue-config + revert, churn forecast) are
verified working end-to-end by `tests/test_e2e_baseline.py`. This spec
is the source of truth for that baseline; changes below this line are
additions since the pre-baseline session notes.

---

## What ORCA Is

ORCA is an AI-native network operations platform using Claude Sonnet as its reasoning engine. It monitors IP/MPLS networks continuously, resolves faults autonomously, detects security breaches, and produces human-readable audit trails in Git.

ORCA is positioned as a **business continuity and judgment-layer** tool — explicitly distinct from IGP protocol resilience (OSPF/IS-IS), which handles primary fault recovery autonomously at the protocol level. ORCA operates above that layer.

### The Two Missions
- **Mission 1** — Keep all link utilization below 90%
- **Mission 2** — Minimize maximum utilization across all links

### Architecture Principle
- **Mathematical algorithms** (CSPF/LP) for provably optimal, sub-millisecond path computation
- **LLM reasoning** (Claude Sonnet) for judgment, context, communication, and novel fault handling
- These serve fundamentally different purposes and must not compete in framing

---

## Infrastructure

| Item | Value |
|------|-------|
| Provider | DigitalOcean SFO2 |
| Droplet size | `s-4vcpu-8gb` |
| Image | `ubuntu-24-04-x64` |
| SSH key IDs | `54443503`, `53273622` |
| Firewall ID | `5a6f549a-8561-4a7e-809a-e8bd6ffeac18` |
| DO API token | `dop_v1_60651458efb36ecb98f382f8f8daa19a086bf4f8444f93ad98d84541258b174d` |
| GitHub repo | `github.com/sireenmalik/orca` (private) |
| GitHub token | `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` |
| Anthropic key | `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` |
| SendGrid key | `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` |
| OPS email | `sireenmalik@gmail.com` |
| Current IP | Changes on each deploy — check `GET /api/health` |

### App on Server
- Docker container: `orca_api_1`
- Port mapping: `80:8000`
- App path: `/opt/orca/`
- Env file: `/opt/orca/.env`
- Init log: `/var/log/orca-init.log`
- Compose file: `docker-compose.yml`

---

## Stack

```
Frontend  React + D3 + Vite         dashboard/src/App.jsx
Backend   FastAPI + WebSocket        api/main.py
Agent     Claude Sonnet              agent/te_agent.py
Adapter   ContainerlabAdapter        agent/adapter.py
Notify    SendGrid + mailto queue    agent/notifications.py
Network   Simulated 6-node ring      ContainerlabAdapter
```

---

## Network Topology (Simulated)

6-node ring: R1 — R2 — R3 — R4 — R5 — R6 — R1, plus cross-links R1-R4 and R2-R5.

**LSPs:**
- `lsp-customer-a` — R1→R4 via [R1,R2,R3,R4], 2.0 Gbps, Enterprise $2.4M ARR
- `lsp-customer-b` — R2→R6 via [R2,R3,R4,R5,R6], 1.5 Gbps, SMB $480K ARR
- `lsp-mgmt` — R1→R6 via [R1,R6], 0.5 Gbps, Internal

**Baseline utilization:** R1-R2: 35%, R2-R3: 40%, R3-R4: 38%, R4-R5: 28%, R5-R6: 32%, R6-R1: 25%, R1-R4: 22%, R2-R5: 24%

**Approved baseline configs** stored in `ContainerlabAdapter.APPROVED_CONFIGS` for R1, R2, R3.

---

## API Endpoints

### State & Agent
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/state` | Full network state (nodes, links, LSPs, alarms) |
| POST | `/api/agent/start` | Start autonomous polling loop |
| POST | `/api/agent/stop` | Stop agent |
| POST | `/api/agent/analyze` | Trigger one analysis cycle |
| WS | `/ws` | WebSocket event stream |

### Demo Controls
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/demo/inject-failure` | Bring a link down |
| POST | `/api/demo/inject-congestion` | Set link utilization |
| POST | `/api/demo/restore-link` | Restore a link |
| POST | `/api/demo/reset` | Full network reset |
| POST | `/api/demo/inject-rogue-config` | Inject unauthorized config on R1 |
| POST | `/api/demo/clear-rogue-config` | Clear rogue config |
| POST | `/api/demo/security-reset` | Clear security alerts, alarms, rogue config |

### Config Proposals
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config-proposals` | List all proposals |
| POST | `/api/config-proposals/{id}/approved` | Approve → triggers stream_approval |
| POST | `/api/config-proposals/{id}/approve` | Alias for above |
| POST | `/api/config-proposals/{id}/rejected` | Reject |
| POST | `/api/config-proposals/{id}/committed` | Mark committed |
| POST | `/api/config-proposals/{id}/saved` | Mark saved |
| DELETE | `/api/config-proposals` | Clear all |

### Security & Churn
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/security-alerts` | List security alerts |
| DELETE | `/api/security-alerts` | Clear alerts |
| GET | `/api/churn-risk` | Live SLA risk + churn probability per LSP |

### Email
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/emails` | List queued emails |
| DELETE | `/api/emails` | Clear queue |
| POST | `/api/emails/{id}/send` | Trigger send |

---

## WebSocket Event Types

All events: `{type, timestamp, data}`. `timestamp` is ISO string.

| Type | Data | Description |
|------|------|-------------|
| `state_update` | `{nodes, links, lsps, alarms}` | Full network state |
| `agent_status` | `{status, message}` | Agent status message |
| `tool_call` | `{tool, inputs}` | Agent calling a tool |
| `tool_result` | `{tool, result}` | Tool result |
| `tool_error` | `{tool, error}` | Tool error |
| `agent_thinking` | `{message}` | Agent reasoning text |
| `git_command` | `{command}` | Git command being run |
| `pr_opened` | `{pr_number, pr_url, message}` | GitHub PR opened |
| `security_alert` | `{alert}` | Security alert raised |
| `security_alarm` | `{node, message}` | Raw security alarm (also handled) |
| `security_revert_proposed` | `{proposal_id, message}` | Revert proposal created |
| `netconf_push` | `{status, message}` | NETCONF config push |
| `churn_risk_update` | `{risks}` | SLA risk scores updated |

---

## Three Use Cases

### Use Case 1 — Network Operations (7-step flow)

1. **Fault injection** — `POST /api/demo/inject-failure {link_id: "R1-R4"}`.
   Adapter marks link down, broadcasts `state_update`. Dashboard paints
   the link red + dashed.
2. **Observe** — agent calls `get_topology`, `get_link_utilization`,
   `get_lsp_state`, `get_alarms`.
3. **Reason + act** — agent reroutes `lsp-customer-a` to `R1→R6→R5→R4`
   and `lsp-customer-b` to `R2→R5→R6`; `lsp-mgmt` stays on `R1→R6`
   (`approval_required: true`). Two emails queue: NOC summary (yellow
   border) + Nokia TAC P1 case (yellow border).
4. **Propose** — `propose_config_change` creates a pending proposal in
   `_config_proposals` with validation_checks + validation_detail +
   device-keyed changes. Agent captures `util_before` (pre-action
   snapshot from `analyze()` cycle start) and `util_after` on the
   proposal; `max_util_*` and `mission_2_improvement_pct` derived.
5. **Approve & push** — operator clicks Approve in Config Modal → frontend
   POSTs `/api/config-proposals/{id}/approved`. `stream_approval` runs
   async:
   - 4 git commands stream (0.6s apart) in agent log
   - NETCONF per-router simulation (0.5s apart)
   - `open_pull_request` opens a real GitHub PR (title `cfg: {title}
     [{timestamp}]`, branch `cfg/{routers}-{ts}`, incident body with
     mission compliance + validation + per-router diff)
   - `write_episode` enriches with util_before/after and the proposal's
     changes, writes `skills/past/episodes/{YYYY-MM}/ep-{ts}.yaml`
     with PR cross-reference header
   - Third email queues: `✅ ORCA Config Deployed — {title} | PR #N`
     (green border). No duplicate: the same proposal cannot be approved
     twice (see Idempotent Approve below).
6. **Duplicate suppression** — after approval `agent._proposal_approved
   = True` prevents re-proposal on the same fault signature until the
   network heals (`has_fault = False`). Security / revert proposals are
   NEVER suppressed by this flag.

### Use Case 2 — Security: Unauthorized Config Detection

1. **Rogue injection** — `POST /api/demo/inject-rogue-config` adds an
   SNMP RW community + an overly-permissive ACL to R1's running config
   (via adapter) plus a provisional `security_alert` in the Security
   tab. No Analyze needed for the alert to appear.
2. **Agent detects + classifies** — on next Analyze (or manual trigger),
   agent calls `detect_config_drift` → `raise_security_alert`. The
   alert is enriched with `classification: management_plane_exposure`
   and a CISA AA24-038A (Salt Typhoon) threat-intel note.
3. **Evidence archive** — `raise_security_alert` opens a git branch
   `security/evidence-{ts}-{node}`, commits `rogue.conf`,
   `approved.conf`, `rogue.diff`, `metadata.yaml` under
   `security/incidents/{ts}-{node}/`, opens an **evidence PR** (archival
   only).
4. **Immediate notifications** — two emails send right away:
   NOC security alert (`🔐 ORCA SECURITY ALERT …`) and
   Nokia TAC P1 case (`[TAC P1] NOKIA — security_violation on {node}`).
5. **Revert proposal** — a config proposal is created with
   `security: True`, `alert_id`, `evidence_url`, and
   `changes[].type = security_revert` showing rogue → baseline diff.
   Red SECURITY badge on the card.
6. **Approve revert** — same `/approved` route; `stream_approval` runs.
   On success the linked security alert is flipped to
   `status = "remediated"` with `remediation_pr_url` +
   `remediation_pr_number` attached, then re-broadcast. Frontend
   renders the alert in green with a ✓ and exposes a "🔀 Remediation PR"
   link next to the evidence PR.

### Use Case 3 — Churn Forecast (live)

The Churn tab's KPIs react to `/api/churn-risk`:

- **Current Churn** = average of per-LSP `churn_probability_pct`.
- **Forecast Q3** = `liveChurn × 0.95` (first forecast month, 5%
  monotonic decay per month thereafter).
- **At-Risk ARR** = sum of `arr_usd` for LSPs with `risk_band ∈
  {at_risk, critical}`.
- **Sparkline** — last history point is the live current churn; forecast
  band retracks as risk bands shift.

See `Churn Model` section for the per-LSP risk score formula.

---

## Config Proposal Object Structure

```python
{
    "id": "cfg-{timestamp}",
    "timestamp": "ISO string",
    "title": "str",
    "reason": "str",
    "validation_checks": {          # booleans
        "syntax": True,
        "semantic": True,
        "mission_1": True,
        "mission_2": True,
        "digital_twin": True,
        "policy": True,
    },
    "validation_detail": {          # human-readable strings
        "syntax": "Valid Nokia SR-OS 22.x syntax",
        "semantic": "All hops reachable, bandwidth available",
        "mission_1": "All links remain below 90% utilization",
        "mission_2": "Max utilization reduced — missions satisfied",
        "digital_twin": "Simulated stable under peak load",
        "policy": "Within policy, no excluded links used",
    },
    "changes": [                    # agent sends 'device' key
        {
            "device": "R3",         # NOT 'node' or 'router'
            "type": "metric_change",
            "current_config": "isis metric 10",
            "new_config": "isis metric 20",
            "diff_summary": "Increase R3-R4 IGP metric from 10 to 20",
        }
    ],
    "projected_improvement": "str",
    "status": "pending|approved|rejected|committed|saved",
    "security": True,               # only on security revert proposals
    "evidence_url": "str",          # only on security proposals
    "trigger_type": "str",
    "trigger_link": "str",
}
```

---

## Security Alert Object Structure

```python
{
    "id": "sec-{timestamp}",
    "timestamp": "ISO string",
    "node": "R1",
    "severity": "critical",
    "type": "unauthorized_config_change",
    "detail": "str",
    "classification": "management_plane_exposure",
    "changes": [...],               # rogue changes detected
    "status": "active",
    "source": "gNMI config drift detection",
    "source_ip": "10.0.3.44",
    "threat_intel": "str",          # CISA reference
    "evidence_url": "str",          # GitHub PR URL
    "provisional": True,            # set before ORCA analyzes, cleared after
}
```

---

## Episode YAML Structure

Stored at: `skills/past/episodes/{YYYY-MM}/ep-{YYYYMMDD-HHMMSS}.yaml`

Key sections: `trigger`, `network_state` (before/after), `lsps_affected`, `decision`, `missions` (M1+M2 with detail), `validation_checks` (with `pass` + `detail` per check), `config_change` (pr_number, pr_url, branch, commit_sha, routers_affected), `notifications_sent`, `learned_constraint`

---

## GitHub Artifacts Per Incident

### Normal Config Change
- Branch: `cfg/{routers}-{timestamp}`
- Files: `config_mgmt/candidate/nokia-lab-sfo2/{R}.conf`, `config_mgmt/diff/nokia-lab-sfo2/{R}.diff`
- PR title: `cfg: {title} [{timestamp}]`

### Security Incident
- Evidence branch: `security/evidence-{timestamp}-{node}`
- Files: `security/incidents/{timestamp}-{node}/rogue.conf`, `approved.conf`, `rogue.diff`, `metadata.yaml`
- Evidence PR: auto (archival only, no approval needed)
- Revert PR: human-gated (same flow as normal config change)

---

## Churn Model

```
risk_score = weighted sum of:
  0.35 × (90% breaches / window)
  0.25 × (time degraded / 1440 min)
  0.20 × (reroute count / 5)
  0.12 × (80% breaches / window)
  0.08 × (85% breaches / window)

churn_prob = logistic(k=0.08, midpoint=60, risk_score) × segment_multiplier

segment_multiplier: Enterprise 0.7×, SMB 1.0×, Consumer 1.4×
```

Risk bands: Healthy (0-25), Watch (26-55), At Risk (56-80), Critical (81-100)
History window: 96 slots = 24h at 15min intervals

---

## Baseline invariants (tests pin these)

1. **Every `/api/config-proposals/{id}/approved` call is idempotent.**
   `_deploying_proposals` set in `api/main.py` ensures `stream_approval`
   is spawned at most once per proposal. Second call returns
   `{"status": "already_deploying"}` without side effects.
2. **Agent sends `device` key** in `changes[]` — consumers must look up
   `ch.get("device") or ch.get("node") or ch.get("router")`.
3. **Episode always carries util_before / util_after** when an agent
   cycle ran. `analyze()` snapshots pre-action utilization; the
   `write_episode` dispatch in `_execute_tool` auto-enriches with that
   snapshot + the latest pending proposal's `changes` + current
   utilization. Per-link values are indented 6 spaces under `links:`.
4. **Module-level `from datetime import datetime`** in
   `agent/te_agent.py`. NO local `datetime` import inside any branch of
   `_execute_tool` (would make the name function-scoped → UnboundLocalError
   in every branch that doesn't import it).
5. **Both `/approved` and `/approve` routes** must be registered on the
   same handler.
6. **Security flow: NOC + TAC emails go out immediately** from
   `raise_security_alert`, not just on Analyze completion. Evidence PR
   + revert proposal are both created before the operator sees
   anything.
7. **Security alert marks `remediated` on revert push.** Matching is
   by `alert_id` when present, else by node against any active alert
   whose node is in `changes[].device`.
8. **`churnHistory` + `churnForecast` arrays are defined at module
   scope** in `dashboard/src/App.jsx`. ChurnTab references them directly;
   missing them throws ReferenceError → whole tab blank.
9. **Agent log panel auto-scroll** respects a 100px bottom-proximity
   check — doesn't snap to bottom when operator is reading earlier
   entries.

## Roadmap

- [ ] Nokia SR-OS adapter via gNMI/NETCONF (~8h)
- [ ] Microsoft Teams integration — bidirectional (~4h)
- [ ] N-1 resilience simulation (~2h)
- [ ] Digital twin scenario testing
- [ ] ServiceNow / PagerDuty integration
