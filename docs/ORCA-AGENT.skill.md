# ORCA Agent Skill
**Read this before touching agent/te_agent.py, agent/adapter.py, or api/main.py.**

---

## Agent Tools (full list)

| Tool | Purpose | Required inputs |
|------|---------|----------------|
| `get_topology` | Network topology | — |
| `get_link_utilization` | Link util% | `link_id?` |
| `get_lsp_state` | All LSPs + paths | — |
| `get_alarms` | Active alarms | — |
| `reroute_lsp` | Move an LSP | `lsp_id`, `new_path: []` |
| `set_link_metric` | Change IGP metric | `link_id`, `metric` |
| `notify_ops_team` | Send NOC email | `subject`, `message`, `severity` |
| `open_tac_case` | Vendor TAC case | `vendor`, `node`, `fault_type`, `severity`, `description` |
| `propose_config_change` | Create human-gated proposal | `title`, `reason`, `changes`, `validation_results?`, `projected_improvement?` |
| `open_pull_request` | Create GitHub branch+PR | `title`, `body`, `device`, `config_content`, `config_path` |
| `write_episode` | Save incident to Git | `trigger_type`, `actions_taken`, `outcome`, `mission_1_satisfied` |
| `detect_config_drift` | Diff running vs approved | `node` |
| `raise_security_alert` | Raise alert + archive evidence | `node`, `severity`, `type`, `detail`, `classification?`, `changes?` |
| `assess_sla_risk` | Churn model per LSP | `window_hours?` |

---

## Agent Action Cycle Order

### Normal fault response:
```
get_topology + get_link_utilization + get_lsp_state + get_alarms  (observe)
reroute_lsp × N                                                   (act)
get_link_utilization                                              (verify M1+M2)
notify_ops_team                                                   (MANDATORY)
open_tac_case vendor="nokia"                                      (escalate)
propose_config_change                                             (config)
open_pull_request                                                 (git)
write_episode                                                     (learn)
assess_sla_risk                                                   (churn)
```

### Security breach cycle:
```
detect_config_drift(node)          (detect)
raise_security_alert(...)          (alert + archive evidence + create revert proposal)
notify_ops_team                    (notify)
write_episode trigger_type="security_violation"  (learn)
```

---

## In-Memory Stores

```python
_config_proposals: list = []    # all proposals
_security_alerts: list = []     # all security alerts

def get_config_proposals() -> list
def get_security_alerts() -> list
def clear_security_alerts()
def update_proposal_status(id, status) -> dict
def clear_proposals()
```

Both are module-level lists. Import at top of any file that needs them:
```python
from agent.te_agent import (get_config_proposals, update_proposal_status,
                             clear_proposals, get_security_alerts, clear_security_alerts,
                             _security_alerts, _config_proposals)
```

---

## propose_config_change Handler

The agent sends `validation_results` (the input key). The handler normalises and stores as `validation_checks` (bool) + `validation_detail` (string):

```python
# Input from agent
"validation_results": {
    "syntax": "✅ Valid Nokia SR-OS 22.x",   # string
    "mission_1": True,                        # or bool
}

# Stored in proposal
"validation_checks": {"syntax": True, "mission_1": True, ...}  # bools
"validation_detail": {"syntax": "Valid Nokia SR-OS 22.x", ...}  # strings
```

The `changes` array uses `device` key (not `node`):
```python
"changes": [{
    "device": "R3",                          # NOT node/router
    "type": "metric_change",
    "current_config": "isis metric 10",
    "new_config": "isis metric 20",
    "diff_summary": "Increase R3-R4 metric from 10 to 20",
}]
```

---

## raise_security_alert Handler

Does five things in sequence:

1. **Builds alert object** with threat intel (CISA AA24-038A reference)
2. **Replaces provisional alert** if one exists for same node (injected by endpoint before ORCA analyzed)
3. **Emits `security_alert`** WebSocket event
4. **Sends security email** via `send_email()` — structured body with evidence URL, threat intel, revert instructions
5. **Archives evidence to Git** — creates `security/evidence-{ts}-{node}` branch with 4 files, opens evidence PR (auto, no human needed)
6. **Creates revert config proposal** — human-gated, appears in Config Proposals with red SECURITY badge

The `provisional` flag: when the demo button injects rogue config, a provisional alert is immediately added to `_security_alerts`. When ORCA runs `raise_security_alert`, it replaces the provisional entry with the enriched alert.

---

## stream_approval Flow (on Approve & Push)

Triggered by `POST /api/config-proposals/{id}/approved`:

```
1. Update proposal status → "approved"
2. Extract changes, validation, routers from proposal object
3. Derive branch: cfg/{sorted_routers}-{timestamp}
4. Derive routers from ch.get("device", ch.get("node", ch.get("router")))
5. Stream 4 git commands via WebSocket (git_command events)
6. Simulate NETCONF push per router (agent_status + tool_result events)
7. Call open_pull_request → full rich PR body
8. Broadcast pr_opened event
9. Call write_episode → enriched YAML with PR cross-reference
10. Send NOC email via send_email() — includes PR link + episode link
11. Broadcast final agent_status: "Incident closed — PR #N | Episode"
```

**Critical:** Both `/approved` AND `/approve` routes must be registered (frontend posts to `/approved`).

---

## open_pull_request (_open_github_pr)

Creates branch, commits per-router config files, opens PR with rich markdown body.

PR body sections:
1. Incident summary table (trigger, LSPs, resolution time, routers)
2. What happened + actions taken (numbered)
3. Mission compliance table (M1 ✅ M2 ✅ with before/after util%)
4. Validation checks table — 3 columns: Check | Result | Detail
5. Per-router diff in `diff` code blocks (+ green, - red)
6. Episode cross-reference path
7. Review instructions

Files committed per router:
- `config_mgmt/candidate/nokia-lab-sfo2/{R}.conf` — clean applied config
- `config_mgmt/diff/nokia-lab-sfo2/{R}.diff` — unified diff with +/- markers

---

## write_episode (_write_episode)

Stores to `skills/past/episodes/{YYYY-MM}/ep-{YYYYMMDD-HHMMSS}.yaml`.

Validation section format in YAML (not flat booleans):
```yaml
validation_checks:
  syntax:
    pass: true
    detail: "Valid Nokia SR-OS 22.x syntax"
  mission_1:
    pass: true
    detail: "All links remain below 90% utilization"
```

Config change cross-reference:
```yaml
config_change:
  pr_number: 31
  pr_url: "https://github.com/..."
  branch: "cfg/R3-20260423-143218"
  commit_sha: "abc123"
  routers_affected: ["R3"]
  changes: [...]
  diff: |
    - isis metric 10
    + isis metric 20
```

---

## detect_config_drift Handler

Reads `adapter._rogue_config[node]` via `get_running_config()`. Returns `drift_detected: True` with `unauthorized_changes` list if rogue config is injected.

```python
result = {
    "drift_detected": True,
    "node": "R1",
    "source_ip": "10.0.3.44",
    "method": "NETCONF direct push — no ORCA PR",
    "unauthorized_changes": [...],
    "summary": "2 unauthorized change(s) detected on R1"
}
```

---

## assess_sla_risk Handler

```python
risk_score = (
  0.35 × (breach_90 / max(slots*0.1, 1))   # M1 violations
  0.25 × (time_degraded / 1440)             # duration
  0.20 × (reroutes / 5)                     # stability
  0.12 × (breach_80 / max(slots*0.2, 1))    # near-threshold
  0.08 × (breach_85 / max(slots*0.05, 1))   # elevated
) × 100

churn_prob = logistic(k=0.08, midpoint=60, x=risk_score) × segment_multiplier
```

Emits `churn_risk_update` WebSocket event.

---

## Adapter Interface

```python
class NetworkAdapter(ABC):
    async def get_topology() -> dict
    async def get_link_utilization(link_id=None) -> dict
    async def get_lsp_state() -> list
    async def get_alarms() -> list
    async def reroute_lsp(lsp_id, new_path) -> dict
    async def set_link_metric(link_id, metric) -> dict
    async def simulate_failure(link_id) -> dict
    async def restore_link(link_id) -> dict
    async def get_full_state() -> NetworkState
```

ContainerlabAdapter additionally provides:
```python
inject_rogue_config(node="R1") -> dict
clear_rogue_config() -> None
get_running_config(node) -> dict      # includes _rogue_meta if injected
get_approved_config(node) -> dict     # from APPROVED_CONFIGS
record_lsp_utilization(lsp_id, util, rerouted=False)
get_lsp_history(lsp_id, window=96) -> list
inject_congestion(link_id, utilization) -> dict
```

---

## notifications.py — Email Queue

`send_email(to, subject, body)` — always queues to `_email_queue`. Returns dict with `email_id`, `mailto`, `message`.

**Dedup rules:** Only deduplicates if exact same subject within 5 minutes AND subject does not contain `PR #`, `Episode`, `Evidence`, `Deployed`, or `security:`. These always go through.

`get_pending_emails()` — returns list for `/api/emails` endpoint.

---

## System Prompt Rules (must not be removed)

- `notify_ops_team` is MANDATORY after every action cycle — never skip
- After link DOWN: both `notify_ops_team` AND `open_tac_case vendor="nokia"`
- After propose_config_change: ALWAYS call `open_pull_request`
- After every cycle: ALWAYS call `write_episode` and `assess_sla_risk`
- Security alarm detected: ALWAYS `detect_config_drift` → `raise_security_alert`
- Config drift without PR is a breach — always investigate and propose revert
