# ORCA — Project Specification
**Autonomous Network Operations & Response Agent**
Version: 33 | Last updated: 2026-04-23

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

### Use Case 1 — Network Operations & Predictive Maintenance
**Flow:** Inject Fault (R1-R4) → Analyze → ORCA reroutes LSPs → Config Proposal → Approve & Push → Git stream → GitHub PR → Episode

**Key demo moments:**
- CSPF path computation in agent log
- Missions satisfied: M1 ✅ M2 ✅
- Config modal: left sidebar (6 validation checks), center diff (red/green), right proposed config, device tabs
- Git commands streaming live in agent log
- GitHub PR with full incident narrative + validation table + per-router diffs
- Episode YAML cross-referenced to PR

### Use Case 2 — Security: Unauthorized Config Detection
**Flow:** Inject Rogue Config → Security tab shows CRITICAL immediately → Analyze → ORCA detects drift → Evidence archived to Git → Evidence PR (auto) → Revert proposal (human-gated) → Approve → NETCONF revert → Episode

**Key demo moments:**
- Security tab updates on button click, no Analyze needed
- Threat intel note: CISA AA24-038A (Salt Typhoon) reference
- Evidence package in `security/incidents/{timestamp}-R1/`: rogue.conf, approved.conf, rogue.diff, metadata.yaml
- Two GitHub items: evidence PR (auto-merged archival) + revert PR (human approval)
- Red SECURITY badge on config proposal card
- Security email card in outbox with evidence PR link

### Use Case 3 — Customer Experience & Churn Forecast
**Flow:** After fault resolution → Churn tab → Live SLA risk scores → Counterfactual panel → Revenue protected

**Key demo moments:**
- Customer-A: risk 12→34, churn 1%→5% WITH ORCA vs 12→71, churn 1%→78% WITHOUT
- Revenue protected: $2.4M ARR
- Churn chart annotated with network incidents
- "without ORCA" red dashed line diverges +1.35% by Aug

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

## Roadmap

- [ ] Nokia SR-OS adapter via gNMI/NETCONF (~8h)
- [ ] Microsoft Teams integration — bidirectional (~4h)
- [ ] N-1 resilience simulation (~2h)
- [ ] Digital twin scenario testing
- [ ] ServiceNow / PagerDuty integration
