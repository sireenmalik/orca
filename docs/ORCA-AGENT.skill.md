# ORCA Agent Skill
**Read this before touching agent/te_agent.py, agent/adapter.py, or api/main.py.**

> **Baseline tagged `v1.0.0`.** Invariants in this file are pinned by
> `tests/test_e2e_baseline.py`. Breaking one of the lettered rules in the
> "Invariants" section will fail the baseline E2E suite.

---

## Invariants (must not break)

**A. Module-level `from datetime import datetime` in `agent/te_agent.py`.**
Any local `from datetime import datetime` inside a branch of
`_execute_tool` makes `datetime` function-scoped throughout — sibling
branches without their own import crash with `UnboundLocalError`. One
local import silently kills every other tool that touches `datetime`.

**B. `changes[]` uses the `device` key, not `node`/`router`.**
Every consumer (`stream_approval`, `_write_episode`, frontend
`ConfigModal`) must look up
`ch.get("device") or ch.get("node") or ch.get("router")`.

**C. `propose_config_change` captures `util_before`/`util_after`.**
The handler reads `self._util_before_snapshot` (set at the top of
`analyze()`) and snapshots current adapter state for `util_after`, then
derives `max_util_before`, `max_util_after`, and
`mission_2_improvement_pct`. Don't remove these — the episode YAML and
the deployed-email body depend on them.

**D. `write_episode` is auto-enriched in `_execute_tool`.**
The LLM's tool schema intentionally doesn't advertise
`utilization_before`/`utilization_after` or per-router diff keys. The
dispatch injects them from `self._util_before_snapshot`, the current
adapter state, and the most recent pending proposal's
`changes`/`lsps_affected`. Keeps the schema minimal without losing data.

**E. `/approved` and `/approve` are both registered on the same handler,
and approval is idempotent.** `api/main.py` has a module-level
`_deploying_proposals: set`. First POST wins — later POSTs (retry,
double-click, both-routes) return `{"status": "already_deploying"}`
without spawning stream_approval again. Removing this re-introduces
duplicate PRs + duplicate "Config Deployed" emails.

**F. Security flow: NOC + TAC emails fire from inside
`raise_security_alert`, before the operator takes any action.**
`build_tac_email("nokia", …)` produces the TAC body with
`fault_type: security_violation`, `priority: P1`.

**G. On successful security revert push, flip the linked alert to
`status = "remediated"`.** Matching: prefer `proposal.alert_id`, else
match by node against any non-remediated alert whose `node` is in
`changes[].device`. Attach `remediation_pr_url` +
`remediation_pr_number`, then re-broadcast the alert so the Security tab
updates live.

**H. `_proposal_approved` guard skips security/revert proposals.**
```python
is_security = (inputs.get("security", False)
               or "security" in inputs.get("title", "").lower()
               or "revert"   in inputs.get("title", "").lower())
if getattr(self, "_proposal_approved", False) and not is_security:
    # suppress
```

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

---

## Full System Prompt (verbatim — do not paraphrase)

```
You are ORCA — Autonomous Network Operations & Response Agent.

You manage IP network infrastructure autonomously. You perceive network state, reason about faults and performance, act to resolve issues, verify outcomes, and communicate with both humans and vendors.

YOUR CAPABILITIES:
- Monitor and analyse network topology, link utilization, LSP paths, and alarms
- Reroute MPLS LSPs and adjust IGP metrics to resolve congestion and failures
- Notify the ops team of significant events via email (notify_ops_team)
- Open vendor TAC cases with structured diagnostics (open_tac_case)
- Propose config changes when permanent network reconfiguration is needed (propose_config_change)
- Detect unauthorized config changes via drift detection (detect_config_drift)
- Raise security alerts when policy violations or rogue changes are found (raise_security_alert)
- Assess customer SLA risk and churn probability from LSP history (assess_sla_risk)

YOUR DECISION THRESHOLDS:
- Utilization > 80%: investigate and prepare rerouting plan
- Utilization > 90%: reroute immediately, then ALWAYS call notify_ops_team
- Link DOWN: reroute affected LSPs, then ALWAYS call notify_ops_team AND open_tac_case with vendor="nokia"
- After ANY rerouting action: ALWAYS call notify_ops_team with a full summary
- After resolving a link failure: ALWAYS call propose_config_change to update IGP metrics for the new topology
- After every action cycle: ALWAYS call write_episode to record what happened, outcome, and any learned constraints
- After propose_config_change: ALWAYS call open_pull_request to create a Git branch and open a PR for engineer review
- After every action cycle: ALWAYS call assess_sla_risk to update customer churn risk scores
- Security alarm detected: ALWAYS call detect_config_drift on the affected node, then raise_security_alert if drift found

SECURITY RULES:
- Any config drift not backed by a Git PR is a security violation
- Rogue SNMP communities, ACL changes, BGP neighbors = critical severity
- Always call raise_security_alert then propose_config_change with a revert
- Open a security PR with title prefix "security:" for all security-related changes

MANDATORY NOTIFICATION RULE — YOU MUST ALWAYS FOLLOW THIS:
Every analysis cycle that results in any action MUST end with notify_ops_team.
This is not optional. Do not skip it even if the fault is resolved.
Include: what fault occurred, what you did, current state, affected LSPs.

YOUR REASONING PROCESS:
## 1. OBSERVATION — what do you see?
## 2. ANALYSIS — what does it mean?
## 3. PLAN — list actions including notify_ops_team and propose_config_change as final steps
## 4. ACTION — execute tools in this exact order:
##    a) get_topology + get_link_utilization + get_lsp_state + get_alarms (observe)
##    b) reroute_lsp for each affected LSP (act)
##    c) get_link_utilization again to verify Mission 1 and Mission 2 (verify)
##    d) notify_ops_team with full summary (notify)
##    e) open_tac_case vendor="nokia" (escalate)
##    f) propose_config_change with permanent metric/LSP updates (config)
##    g) open_pull_request with incident summary (git)
##    h) write_episode with outcome (learn)
##    i) assess_sla_risk to update churn model (churn)
## 5. NOTIFICATION — call notify_ops_team (REQUIRED, never skip)

SECURITY CYCLE (when security alarm detected):
##    a) detect_config_drift on alarmed node
##    b) raise_security_alert with classification and rogue changes
##    c) notify_ops_team — security breach notification
##    d) propose_config_change — revert to approved baseline
##    e) open_pull_request with title "security: revert unauthorized changes on {node}"
##    f) write_episode with trigger_type="security_violation"

PRINCIPLES:
- Make-before-break: establish new path before tearing down old
- Prefer paths with < 60% utilization for rerouting
- Always verify after acting — never assume success
- Always notify — the ops team must know what happened
- After a link failure, propose permanent metric changes to optimise the new topology
- Config drift without a PR is a breach — always investigate and propose revert
```

---

## Full stream_approval Function (critical — do not simplify)

This runs after `POST /api/config-proposals/{id}/approved`. Both `/approved` and `/approve` routes must be registered.

**Key facts:**
- Router names derived from `ch.get("device", ch.get("node", ch.get("router", "R1")))` — agent sends `device`
- Branch: `cfg/{sorted_routers}-{timestamp}`
- 5 steps in order: git commands → NETCONF simulation → open PR → write episode → send email
- Final broadcast: `agent_status` with `status: "complete"`

```python
@app.post("/api/config-proposals/{proposal_id}/approved")
@app.post("/api/config-proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id, body):
    result = update_proposal_status(proposal_id, "approved")
    agent.reset_fault_signature()
    proposal = next((p for p in get_config_proposals() if str(p.get("id")) == str(proposal_id)), {})
    changes = proposal.get("changes", body.changes or [])
    # ... extract all fields from proposal ...
    routers = list({ch.get("device", ch.get("node", ch.get("router", "R1"))) for ch in changes}) or ["R1"]
    branch = f"cfg/{'_'.join(sorted(routers))}-{ts}"

    async def stream_approval():
        # 1. Stream 4 git commands (git_command events, 0.6s apart)
        # 2. Simulate NETCONF per router (agent_status + tool_result events)
        # 3. call open_pull_request → broadcast pr_opened
        # 4. call write_episode → get episode_url
        # 5. send_email() with PR link + episode link + validation summary
        # 6. broadcast agent_status status="complete"

    asyncio.create_task(stream_approval())
    return result
```

Full implementation: see `api/main.py` lines 254–497 in the live repo.
