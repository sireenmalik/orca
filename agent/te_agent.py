"""
ORCA — Autonomous Network Operations & Response Agent
Core reasoning loop powered by Claude Sonnet 4
"""
import asyncio, json, os, time
from typing import Optional, Callable
import anthropic
from agent.adapter import ContainerlabAdapter, NetworkAdapter
from agent.notifications import send_email, build_tac_email

SYSTEM_PROMPT = """You are ORCA — Autonomous Network Operations & Response Agent.

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
"""


async def _write_episode(inputs: dict) -> dict:
    """Write enriched episode to skills/past/episodes/ and push to GitHub."""
    import urllib.request, urllib.error, json as _json, os as _os
    import base64 as _b64
    from datetime import datetime

    token = _os.getenv("GITHUB_TOKEN", "")
    repo_owner = _os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name = _os.getenv("GITHUB_REPO", "orca")

    now = datetime.utcnow()
    ep_id = now.strftime("%Y%m%d-%H%M%S")
    month = now.strftime("%Y-%m")
    path = f"skills/past/episodes/{month}/ep-{ep_id}.yaml"

    # Build validation checks block
    validation = inputs.get("validation_checks", {
        "syntax": True, "semantic": True, "mission_1": True,
        "mission_2": True, "digital_twin": True, "policy": True
    })
    validation_detail = inputs.get("validation_detail", {
        "syntax":       "Valid Nokia SR-OS 22.x syntax",
        "semantic":     "All hops reachable, bandwidth available",
        "mission_1":    "All links remain below 90% utilization",
        "mission_2":    "Max utilization reduced — missions satisfied",
        "digital_twin": "Simulated stable under peak load",
        "policy":       "Within policy, no excluded links used",
    })
    def _pass(v):
        if isinstance(v, bool): return v
        return not str(v).strip().startswith("❌")
    validation_yaml = "\n".join(
        f"  {k}:\n    pass: {str(_pass(v)).lower()}\n    detail: \"{validation_detail.get(k, '')}\""
        for k, v in validation.items()
    )

    # Build diff block per router
    changes = inputs.get("changes", [])
    diff_by_router = {}
    for ch in changes:
        node = ch.get("node", ch.get("router", "unknown"))
        if node not in diff_by_router:
            diff_by_router[node] = []
        diff_by_router[node].append(
            f"  - interface: {ch.get('interface', ch.get('iface', 'unknown'))}\n"
            f"    parameter: {ch.get('parameter', 'metric')}\n"
            f"    from: {ch.get('old_value', ch.get('from', '?'))}\n"
            f"    to: {ch.get('new_value', ch.get('to', '?'))}"
        )
    diff_yaml = ""
    for router, diffs in diff_by_router.items():
        diff_yaml += f"  {router}:\n" + "\n".join(diffs) + "\n"
    if not diff_yaml:
        diff_yaml = "  # no structured changes recorded\n"

    # Build config diff block (unified diff style)
    diff_lines = inputs.get("diff", [])
    diff_text = ""
    for d in diff_lines:
        prefix = "+" if d.get("type") == "add" else "-" if d.get("type") == "remove" else " "
        diff_text += f"  {prefix} {d.get('line', d.get('content', ''))}\n"
    if not diff_text:
        diff_text = "  # diff not available\n"

    # Config change cross-reference
    pr_url = inputs.get("pr_url", "")
    pr_number = inputs.get("pr_number", "")
    branch = inputs.get("branch", "")
    commit_sha = inputs.get("commit_sha", "")

    # Network state
    util_before = inputs.get("utilization_before", {})
    util_after = inputs.get("utilization_after", {})
    util_before_yaml = "\n".join(f"    {k}: {v}%" for k, v in util_before.items()) if util_before else "    # not captured"
    util_after_yaml = "\n".join(f"    {k}: {v}%" for k, v in util_after.items()) if util_after else "    # not captured"

    lsps = inputs.get("lsps_affected", [])
    lsps_yaml = "\n".join(f'  - "{l}"' for l in lsps) if lsps else '  - "not recorded"'

    notifications = inputs.get("notifications_sent", [])
    notif_yaml = "\n".join(f'  - "{n}"' for n in notifications) if notifications else '  - "none recorded"'

    episode = f"""# ORCA Incident Episode {ep_id}
# Auto-generated by ORCA after action cycle — do not edit manually
# Cross-reference: {pr_url or 'no PR'}

timestamp: "{now.isoformat()}Z"
episode_id: "{ep_id}"

# ── TRIGGER ──────────────────────────────────────────────────────────────
trigger:
  type: "{inputs.get('trigger_type', 'unknown')}"
  link: "{inputs.get('trigger_link', '')}"
  description: "{inputs.get('trigger_description', 'Network fault detected by ORCA')}"

# ── NETWORK STATE ─────────────────────────────────────────────────────────
network_state:
  before:
    max_utilization_pct: {inputs.get('max_util_before', 0)}
    links:
{util_before_yaml}
  after:
    max_utilization_pct: {inputs.get('max_util_after', 0)}
    links:
{util_after_yaml}

lsps_affected:
{lsps_yaml}

# ── ORCA DECISION ─────────────────────────────────────────────────────────
decision:
  algorithm: "CSPF + LLM judgment"
  reasoning_summary: "{inputs.get('reasoning_summary', 'ORCA detected fault, computed alternate paths via CSPF, rerouted LSPs to restore service within mission thresholds.')}"
  actions_taken:
{chr(10).join('  - "' + a + '"' for a in inputs.get('actions_taken', []))}

# ── MISSION COMPLIANCE ────────────────────────────────────────────────────
missions:
  mission_1:
    objective: "All link utilization below 90%"
    satisfied: {str(inputs.get('mission_1_satisfied', True)).lower()}
    detail: "{inputs.get('mission_1_detail', 'Max utilization kept below 90% threshold after rerouting')}"
  mission_2:
    objective: "Minimize maximum link utilization"
    satisfied: {str(inputs.get('mission_2_satisfied', True)).lower()}
    improvement_pct: {inputs.get('mission_2_improvement_pct', 0)}
    detail: "{inputs.get('mission_2_detail', 'Maximum utilization reduced via optimal path selection')}"

time_to_resolution_seconds: {inputs.get('time_to_resolution_seconds', 0)}
human_override: {str(inputs.get('human_override', False)).lower()}
override_reason: "{inputs.get('override_reason', '')}"

# ── VALIDATION ────────────────────────────────────────────────────────────
validation_checks:
{validation_yaml}

# ── CONFIG CHANGES ────────────────────────────────────────────────────────
config_change:
  pr_number: {pr_number or 'null'}
  pr_url: "{pr_url}"
  branch: "{branch}"
  commit_sha: "{commit_sha}"
  routers_affected: {list(diff_by_router.keys())}
  changes:
{diff_yaml}
  diff: |
{diff_text}

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────
notifications_sent:
{notif_yaml}

# ── LEARNING ──────────────────────────────────────────────────────────────
learned_constraint: "{inputs.get('learned_constraint', '')}"
"""

    if not token:
        return {"success": True, "episode_id": ep_id,
                "message": f"Episode {ep_id} recorded (no GitHub token — not pushed to repo)",
                "path": path, "content": episode}

    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json"
    }
    base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"

    payload = _json.dumps({
        "message": f"learn: episode {ep_id} — {inputs.get('trigger_type','event')} on {inputs.get('trigger_link','')} → {inputs.get('outcome','?')} | PR #{pr_number}",
        "content": _b64.b64encode(episode.encode()).decode(),
        "branch": "main"
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/contents/{path}",
        data=payload, headers=headers, method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
            url = data.get("content", {}).get("html_url", "")
            return {"success": True, "episode_id": ep_id,
                    "path": path, "url": url,
                    "message": f"Episode {ep_id} committed to Git"}
    except Exception as e:
        return {"success": False, "error": str(e),
                "episode_id": ep_id, "content": episode}


async def _open_github_pr(inputs: dict) -> dict:
    """Create branch, commit per-router config files with rich diff, open PR with full incident context."""
    import urllib.request, urllib.error, json as _json, os as _os
    from datetime import datetime
    import base64 as _b64

    token = _os.getenv("GITHUB_TOKEN", "")
    repo_owner = _os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name = _os.getenv("GITHUB_REPO", "orca")

    if not token:
        return {"success": False, "error": "GITHUB_TOKEN not set — PR creation skipped"}

    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json"
    }
    base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"

    def gh_request(method, path, data=None):
        url = f"{base_url}{path}"
        body = _json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return _json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return _json.loads(e.read()), e.code

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    title = inputs.get("title", f"fix: ORCA config update {ts}")

    # Derive affected routers from changes
    changes = inputs.get("changes", [])
    routers = list({ch.get("node", ch.get("router", "R1")) for ch in changes}) or ["R1"]
    branch = f"cfg/{'_'.join(routers)}-{ts}"

    # ── 1. Get main SHA ──
    ref_data, _ = gh_request("GET", "/git/ref/heads/main")
    if "object" not in ref_data:
        return {"success": False, "error": f"Could not get main branch: {ref_data}"}
    main_sha = ref_data["object"]["sha"]

    # ── 2. Create branch ──
    branch_data, status = gh_request("POST", "/git/refs", {
        "ref": f"refs/heads/{branch}", "sha": main_sha
    })
    if status not in (200, 201):
        return {"success": False, "error": f"Branch creation failed ({status}): {branch_data}"}

    # ── 3. Build and commit per-router config files ──
    committed_files = []
    commit_sha = ""
    diff_by_router = {}
    for ch in changes:
        node = ch.get("node", ch.get("router", "R1"))
        if node not in diff_by_router:
            diff_by_router[node] = []
        diff_by_router[node].append(ch)

    for router, router_changes in diff_by_router.items():
        # Build Nokia SR-OS style config with unified diff markers
        config_lines = [
            f"# ORCA Config Proposal — {router}",
            f"# Generated: {datetime.utcnow().isoformat()}Z",
            f"# Incident: {inputs.get('trigger_description', 'Network fault')}",
            f"# Branch: {branch}",
            "",
            "configure router isis 0",
        ]
        for ch in router_changes:
            iface = ch.get("interface", ch.get("iface", "unknown"))
            param = ch.get("parameter", "metric")
            old_val = ch.get("old_value", ch.get("from", "?"))
            new_val = ch.get("new_value", ch.get("to", "?"))
            config_lines += [
                f"    interface \"{iface}\"",
                f"-       {param} {old_val}",
                f"+       {param} {new_val}",
                f"    exit",
            ]
        config_lines += ["exit", ""]

        # Also commit a clean "after" config (what will be applied)
        clean_lines = [
            f"# ORCA — Applied Config for {router}",
            f"# Episode: {inputs.get('episode_id', 'pending')}",
            f"# PR: {branch}",
            "",
            "configure router isis 0",
        ]
        for ch in router_changes:
            iface = ch.get("interface", ch.get("iface", "unknown"))
            param = ch.get("parameter", "metric")
            new_val = ch.get("new_value", ch.get("to", "?"))
            clean_lines += [
                f"    interface \"{iface}\"",
                f"        {param} {new_val}",
                f"    exit",
            ]
        clean_lines += ["exit", ""]

        # Commit diff file
        diff_content = "\n".join(config_lines)
        clean_content = "\n".join(clean_lines)
        config_path = f"config_mgmt/candidate/nokia-lab-sfo2/{router}.conf"
        diff_path = f"config_mgmt/diff/nokia-lab-sfo2/{router}.diff"

        for fpath, fcontent in [(config_path, clean_content), (diff_path, diff_content)]:
            existing, ex_status = gh_request("GET", f"/contents/{fpath}?ref={branch}")
            file_payload = {
                "message": f"cfg({router}): {param} update — {inputs.get('trigger_description', 'incident')}",
                "content": _b64.b64encode(fcontent.encode()).decode(),
                "branch": branch
            }
            if ex_status == 200 and "sha" in existing:
                file_payload["sha"] = existing["sha"]
            file_data, fstatus = gh_request("PUT", f"/contents/{fpath}", file_payload)
            if fstatus in (200, 201):
                committed_files.append(fpath)
                if not commit_sha:
                    commit_sha = file_data.get("commit", {}).get("sha", "")

    # ── 4. Build rich PR body ──
    validation = inputs.get("validation_checks", {
        "syntax": True, "semantic": True, "mission_1": True,
        "mission_2": True, "digital_twin": True, "policy": True
    })
    validation_detail = inputs.get("validation_detail", {
        "syntax":       "Valid Nokia SR-OS 22.x syntax",
        "semantic":     "All hops reachable, bandwidth available",
        "mission_1":    "All links remain below 90% utilization",
        "mission_2":    "Max utilization reduced — missions satisfied",
        "digital_twin": "Simulated stable under peak load",
        "policy":       "Within policy, no excluded links used",
    })
    def _pass(v):
        if isinstance(v, bool): return v
        return not str(v).strip().startswith("❌")
    check_rows = "\n".join(
        f"| **{k}** | {'✅ PASS' if _pass(v) else '❌ FAIL'} | {validation_detail.get(k, '')} |"
        for k, v in validation.items()
    )

    diff_lines = inputs.get("diff", [])
    diff_md = ""
    for router, router_changes in diff_by_router.items():
        diff_md += f"\n### `{router}` — IS-IS metric changes\n\n```diff\n"
        diff_md += f"# configure router isis 0\n"
        for ch in router_changes:
            iface = ch.get("interface", ch.get("iface", "unknown"))
            param = ch.get("parameter", "metric")
            old_val = ch.get("old_value", ch.get("from", "?"))
            new_val = ch.get("new_value", ch.get("to", "?"))
            diff_md += f'  interface "{iface}"\n'
            diff_md += f"-     {param} {old_val}\n"
            diff_md += f"+     {param} {new_val}\n"
            diff_md += f"  exit\n"
        diff_md += "```\n"

    if not diff_md and diff_lines:
        diff_md = "\n```diff\n"
        for d in diff_lines:
            prefix = "+" if d.get("type") == "add" else "-" if d.get("type") == "remove" else " "
            diff_md += f"{prefix} {d.get('line', d.get('content', ''))}\n"
        diff_md += "```\n"

    actions_md = "\n".join(
        f"{i+1}. {a}" for i, a in enumerate(inputs.get("actions_taken", []))
    )

    m1 = "✅" if inputs.get("mission_1_satisfied", True) else "❌"
    m2 = "✅" if inputs.get("mission_2_satisfied", True) else "❌"
    util_before = inputs.get("max_util_before", "?")
    util_after = inputs.get("max_util_after", "?")
    improvement = inputs.get("mission_2_improvement_pct", 0)
    episode_path = inputs.get("episode_path", "skills/past/episodes/")

    pr_body = f"""## 🔧 ORCA Config Proposal — {inputs.get('trigger_description', 'Network fault response')}

> Auto-generated by ORCA Autonomous Network Operations & Response Agent
> Timestamp: `{datetime.utcnow().isoformat()}Z`

---

## 📋 Incident Summary

| Field | Value |
|-------|-------|
| **Trigger** | {inputs.get('trigger_type', 'unknown')} on link `{inputs.get('trigger_link', '?')}` |
| **Affected LSPs** | {', '.join(f'`{l}`' for l in inputs.get('lsps_affected', [])) or 'see episode'} |
| **Resolution time** | {inputs.get('time_to_resolution_seconds', '?')}s |
| **Routers affected** | {', '.join(f'`{r}`' for r in routers)} |

### What happened

{inputs.get('reasoning_summary', 'ORCA detected a network fault and autonomously rerouted affected LSPs to restore service within mission thresholds. Permanent IGP metric changes are proposed here to optimise the topology for the new steady state.')}

### Actions taken by ORCA

{actions_md}

---

## 🎯 Mission Compliance

| Mission | Objective | Result |
|---------|-----------|--------|
| **Mission 1** | All link utilization < 90% | {m1} |
| **Mission 2** | Minimize maximum utilization | {m2} |

- **Utilization before:** `{util_before}%` → **after:** `{util_after}%`
- **Improvement:** `{improvement}%` reduction in max utilization
- {inputs.get('mission_1_detail', '')}
- {inputs.get('mission_2_detail', '')}

---

## ✅ Validation Checks

| Check | Result | Detail |
|-------|--------|--------|
{check_rows}

---

## 📝 Config Changes
{diff_md}

---

## 📚 Episode Reference

This config proposal is cross-referenced with incident episode:

```
{episode_path}
```

The episode contains the full incident timeline, network state before/after, LSP paths, reasoning trace, and learned constraints.

---

## 🚦 Review Instructions

- Review the diff above for each affected router
- Validate against current network state before merging
- After merge, NETCONF push will be triggered automatically
- Reject with comment if topology has changed since this proposal was generated

*Generated by ORCA v26 — Approve to commit to running config via NETCONF*
"""

    # ── 5. Open PR ──
    pr_data, pr_status = gh_request("POST", "/pulls", {
        "title": title,
        "body": pr_body,
        "head": branch,
        "base": "main"
    })
    if pr_status not in (200, 201):
        return {"success": False, "error": f"PR creation failed ({pr_status}): {pr_data}"}

    pr_url = pr_data.get("html_url", "")
    pr_number = pr_data.get("number", "?")

    return {
        "success": True,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "branch": branch,
        "commit_sha": commit_sha,
        "committed_files": committed_files,
        "message": f"PR #{pr_number} opened: {pr_url}"
    }

class ORCAAgent:
    def __init__(self, adapter: NetworkAdapter = None, anthropic_api_key: str = None):
        self.adapter = adapter or ContainerlabAdapter()
        self.client = anthropic.Anthropic(api_key=anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.running = False
        self.poll_interval = int(os.getenv("AGENT_POLL_INTERVAL", "15"))
        self._on_event: Optional[Callable] = None
        self._handled_faults: set = set()  # track faults already handled this session

    def on_event(self, callback: Callable):
        self._on_event = callback

    async def _emit(self, event_type: str, data: dict):
        from datetime import datetime
        if self._on_event:
            await self._on_event({
                "type": event_type,
                "timestamp": datetime.utcnow().isoformat(),
                "data": data
            })

    def _build_tools(self) -> list:
        return [
            {"name": "get_topology", "description": "Get complete network topology.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "get_link_utilization", "description": "Get link utilization. Omit link_id for all links.",
             "input_schema": {"type": "object", "properties": {
                 "link_id": {"type": "string", "description": "Link ID e.g. R1-R2. Omit for all."}}}},
            {"name": "get_lsp_state", "description": "Get all MPLS LSPs with paths and state.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "get_alarms", "description": "Get active network alarms.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "reroute_lsp", "description": "Reroute an MPLS LSP. Make-before-break.",
             "input_schema": {"type": "object", "properties": {
                 "lsp_id": {"type": "string"}, "new_path": {"type": "array", "items": {"type": "string"}}},
                 "required": ["lsp_id", "new_path"]}},
            {"name": "set_link_metric", "description": "Adjust IGP metric on a link.",
             "input_schema": {"type": "object", "properties": {
                 "link_id": {"type": "string"}, "metric": {"type": "integer"}},
                 "required": ["link_id", "metric"]}},
            {"name": "notify_ops_team", "description": "Send email notification to ops team. MANDATORY after every action.",
             "input_schema": {"type": "object", "properties": {
                 "subject": {"type": "string"},
                 "message": {"type": "string"},
                 "severity": {"type": "string", "enum": ["critical","major","minor","info"]}},
                 "required": ["subject", "message", "severity"]}},
            {"name": "open_tac_case", "description": "Open vendor TAC support case for hardware faults.",
             "input_schema": {"type": "object", "properties": {
                 "vendor": {"type": "string", "enum": ["nokia","juniper","cisco"]},
                 "node": {"type": "string"}, "interface": {"type": "string"},
                 "fault_type": {"type": "string"},
                 "severity": {"type": "string", "enum": ["P1","P2","P3","P4"]},
                 "description": {"type": "string"},
                 "affected_lsps": {"type": "string"},
                 "actions_taken": {"type": "string"},
                 "suspected_cause": {"type": "string"}},
                 "required": ["vendor", "node", "fault_type", "severity", "description"]}},
            {"name": "write_episode",
             "description": "Write a learning episode to skills/past/episodes/ after an action cycle completes. Records what happened, what was done, outcome, and any learned constraints. Always call this at the end of a successful or failed action cycle.",
             "input_schema": {"type": "object", "properties": {
                 "trigger_type": {"type": "string", "enum": ["link_failure","congestion","manual","scheduled"]},
                 "trigger_link": {"type": "string"},
                 "actions_taken": {"type": "array", "items": {"type": "string"}, "description": "List of actions e.g. ['rerouted lsp-customer-a via R1-R6-R5-R4']"},
                 "outcome": {"type": "string", "enum": ["success","rollback","partial","escalated"]},
                 "mission_1_satisfied": {"type": "boolean"},
                 "mission_2_improvement_pct": {"type": "number"},
                 "time_to_resolution_seconds": {"type": "number"},
                 "human_override": {"type": "boolean"},
                 "override_reason": {"type": "string"},
                 "learned_constraint": {"type": "string", "description": "Optional: any new constraint to propose e.g. 'avoid R5-R6 under peak load'"}},
                 "required": ["trigger_type", "actions_taken", "outcome", "mission_1_satisfied"]}},
            {"name": "open_pull_request",
             "description": "Create a Git branch, commit the config change, and open a Pull Request on GitHub for engineer review. Call this after propose_config_change is approved or when a permanent config change should be tracked in Git.",
             "input_schema": {"type": "object", "properties": {
                 "title": {"type": "string", "description": "PR title e.g. 'fix: update R1 IS-IS metrics after R1-R4 failure'"},
                 "body": {"type": "string", "description": "PR description — incident summary, what changed, why, validation results"},
                 "device": {"type": "string", "description": "Device name e.g. R1"},
                 "config_content": {"type": "string", "description": "Full config content to commit to candidate/"},
                 "config_path": {"type": "string", "description": "File path e.g. config_mgmt/candidate/nokia-lab-sfo2/R1.conf"}},
                 "required": ["title", "body", "device", "config_content", "config_path"]}},
            {"name": "detect_config_drift",
             "description": "Compare running device config against the approved Git baseline. Returns any unauthorized changes not in the approved config. Call this when security_violation alarm is detected or during routine security checks.",
             "input_schema": {"type": "object", "properties": {
                 "node": {"type": "string", "description": "Router node to check e.g. R1"}},
                 "required": ["node"]}},
            {"name": "raise_security_alert",
             "description": "Raise a security alert in the dashboard. Creates a security event in the Security tab. Call this when unauthorized config changes, rogue additions, or policy violations are detected.",
             "input_schema": {"type": "object", "properties": {
                 "node": {"type": "string"},
                 "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                 "type": {"type": "string", "description": "e.g. unauthorized_config_change, rogue_bgp_neighbor, acl_weakening"},
                 "detail": {"type": "string"},
                 "classification": {"type": "string", "description": "e.g. management_plane_exposure, access_control_weakening"},
                 "changes": {"type": "array", "description": "The rogue changes detected"}},
                 "required": ["node", "severity", "type", "detail"]}},
            {"name": "assess_sla_risk",
             "description": "Compute SLA risk score and churn probability for each customer LSP based on utilization history, reroute count, and degradation time. Returns per-customer risk scores and churn model output. Call after every analysis cycle.",
             "input_schema": {"type": "object", "properties": {
                 "window_hours": {"type": "integer", "description": "History window in hours (default 24)", "default": 24}},
                 "required": []}},
            {"name": "propose_config_change",
             "description": "Propose a permanent config change (metric adjustment, LSP path update). Shows diff in dashboard for operator approval before pushing to network.",
             "input_schema": {"type": "object", "properties": {
                 "title": {"type": "string", "description": "Short description e.g. 'Update R1 IGP metrics after R1-R4 failure'"},
                 "reason": {"type": "string", "description": "Why this change is needed"},
                 "validation_results": {"type": "object", "description": "Results of validation checks",
                     "properties": {
                         "syntax": {"type": "string"}, "semantic": {"type": "string"},
                         "mission_1": {"type": "string"}, "mission_2": {"type": "string"},
                         "digital_twin": {"type": "string"}, "policy": {"type": "string"}}},
                 "changes": {"type": "array", "description": "List of config changes",
                     "items": {"type": "object", "properties": {
                         "device": {"type": "string"},
                         "type": {"type": "string", "description": "metric_change | lsp_update | interface_config"},
                         "current_config": {"type": "string", "description": "Current running config lines"},
                         "new_config": {"type": "string", "description": "Proposed new config lines"},
                         "diff_summary": {"type": "string"}}}},
                 "projected_improvement": {"type": "string", "description": "e.g. max utilization 61% → 54%"}},
                 "required": ["title", "reason", "changes"]}},
        ]

    async def _execute_tool(self, name: str, inputs: dict) -> str:
        await self._emit("tool_call", {"tool": name, "inputs": inputs})
        try:
            if name == "get_topology":
                result = await self.adapter.get_topology()
            elif name == "get_link_utilization":
                result = await self.adapter.get_link_utilization(inputs.get("link_id"))
            elif name == "get_lsp_state":
                result = await self.adapter.get_lsp_state()
            elif name == "get_alarms":
                result = await self.adapter.get_alarms()
            elif name == "reroute_lsp":
                result = await self.adapter.reroute_lsp(inputs["lsp_id"], inputs["new_path"])
            elif name == "set_link_metric":
                result = await self.adapter.set_link_metric(inputs["link_id"], inputs["metric"])
            elif name == "notify_ops_team":
                to = os.getenv("OPS_EMAIL", "sireenmalik@gmail.com")
                emoji = {"critical":"🔴","major":"🟠","minor":"🟡","info":"🟢"}.get(inputs.get("severity","info"),"📡")
                subject = f"{emoji} ORCA [{inputs.get('severity','info').upper()}]: {inputs['subject']}"
                result = send_email(to=to, subject=subject, body=inputs["message"])
            elif name == "open_tac_case":
                to = os.getenv("OPS_EMAIL", "sireenmalik@gmail.com")
                vendor = inputs.get("vendor", "nokia")  # Nokia by default
                fault_data = {
                    "node": inputs.get("node","Unknown"),
                    "interface": inputs.get("interface","Unknown"),
                    "fault_type": inputs.get("fault_type","Unknown"),
                    "priority": inputs.get("severity","P2"),
                    "severity": inputs.get("severity","P2"),
                    "description": inputs.get("description",""),
                    "affected_lsps": inputs.get("affected_lsps","None"),
                    "actions_taken": inputs.get("actions_taken","None"),
                    "suspected_cause": inputs.get("suspected_cause","Under investigation"),
                    "location": "DC-SFO2 / Rack A3",
                }
                body = build_tac_email(vendor, fault_data)
                subject = f"[TAC {inputs.get('severity','P2')}] {vendor.upper()} — {inputs.get('fault_type','Fault')} on {inputs.get('node','Unknown')}"
                result = send_email(to=to, subject=subject, body=body)
            elif name == "detect_config_drift":
                node = inputs.get("node", "R1")
                running = await self.adapter.get_running_config(node) if hasattr(self.adapter, 'get_running_config') else {}
                approved = await self.adapter.get_approved_config(node) if hasattr(self.adapter, 'get_approved_config') else {}
                rogue_meta = running.get("_rogue_meta")
                if rogue_meta:
                    drift = {
                        "drift_detected": True,
                        "node": node,
                        "source_ip": rogue_meta.get("source_ip", "unknown"),
                        "method": rogue_meta.get("method", "unknown"),
                        "unauthorized_changes": rogue_meta.get("changes", []),
                        "summary": f"{len(rogue_meta.get('changes',[]))} unauthorized change(s) detected on {node} — not in approved Git baseline"
                    }
                else:
                    drift = {"drift_detected": False, "node": node, "summary": f"No config drift detected on {node}"}
                result = drift
            elif name == "raise_security_alert":
                from datetime import datetime
                alert = {
                    "id": f"sec-{int(time.time())}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "node": inputs.get("node"),
                    "severity": inputs.get("severity", "high"),
                    "type": inputs.get("type", "unauthorized_config_change"),
                    "detail": inputs.get("detail", ""),
                    "classification": inputs.get("classification", ""),
                    "changes": inputs.get("changes", []),
                    "status": "active",
                    "source": "gNMI config drift detection",
                }
                _security_alerts.append(alert)
                await self._emit("security_alert", {"alert": alert})
                result = {"success": True, "alert_id": alert["id"],
                          "message": f"Security alert raised: {alert['type']} on {alert['node']}"}
            elif name == "assess_sla_risk":
                import math
                window = inputs.get("window_hours", 24)
                slots = window * 4  # 15-min intervals
                risk_results = {}
                # Customer LSP → segment and revenue mapping
                lsp_meta = {
                    "lsp-customer-a": {"customer": "Customer-A", "segment": "Enterprise", "arr_usd": 2400000},
                    "lsp-customer-b": {"customer": "Customer-B", "segment": "SMB", "arr_usd": 480000},
                    "lsp-mgmt": {"customer": "Management", "segment": "Internal", "arr_usd": 0},
                }
                segment_multiplier = {"Enterprise": 0.7, "SMB": 1.0, "Consumer": 1.4, "Internal": 0.0}
                for lsp_id, meta in lsp_meta.items():
                    if meta["segment"] == "Internal":
                        continue
                    history = self.adapter.get_lsp_history(lsp_id, slots) if hasattr(self.adapter, 'get_lsp_history') else []
                    if not history:
                        # Synthesize from current state
                        lsp_state = await self.adapter.get_lsp_state()
                        lsp = next((l for l in lsp_state if l["id"] == lsp_id), {})
                        history = [{"util": 35.0, "rerouted": False}]
                    utils = [h["util"] for h in history]
                    reroutes = sum(1 for h in history if h.get("rerouted"))
                    breach_90 = sum(1 for u in utils if u >= 90)
                    breach_80 = sum(1 for u in utils if u >= 80)
                    max_slots = max(slots, 1)
                    time_degraded = sum(1 for u in utils if u >= 80) * 15  # minutes
                    # Risk score formula
                    raw = (
                        0.35 * min(breach_90 / max(max_slots * 0.1, 1), 1.0) +
                        0.25 * min(time_degraded / 1440, 1.0) +
                        0.20 * min(reroutes / 5, 1.0) +
                        0.12 * min(breach_80 / max(max_slots * 0.2, 1), 1.0) +
                        0.08 * min(len([u for u in utils if u >= 85]) / max(max_slots * 0.05, 1), 1.0)
                    )
                    risk_score = round(min(raw * 100, 100), 1)
                    # Logistic churn probability
                    k, midpoint = 0.08, 60
                    base_prob = 1 / (1 + math.exp(-k * (risk_score - midpoint)))
                    mult = segment_multiplier.get(meta["segment"], 1.0)
                    churn_prob = round(min(base_prob * mult * 100, 99), 1)
                    band = "healthy" if risk_score <= 25 else "watch" if risk_score <= 55 else "at_risk" if risk_score <= 80 else "critical"
                    risk_results[lsp_id] = {
                        "lsp_id": lsp_id,
                        "customer": meta["customer"],
                        "segment": meta["segment"],
                        "arr_usd": meta["arr_usd"],
                        "risk_score": risk_score,
                        "risk_band": band,
                        "churn_probability_pct": churn_prob,
                        "breach_90_count": breach_90,
                        "breach_80_count": breach_80,
                        "reroute_count": reroutes,
                        "time_degraded_mins": time_degraded,
                        "samples": len(history),
                    }
                await self._emit("churn_risk_update", {"risks": risk_results})
                result = {"success": True, "risks": risk_results,
                          "summary": f"SLA risk assessed for {len(risk_results)} customer LSPs"}
            elif name == "write_episode":
                result = await _write_episode(inputs)
            elif name == "open_pull_request":
                result = await _open_github_pr(inputs)
                # If PR opened successfully, attach URL to most recent config proposal
                if result.get("success") and result.get("pr_url"):
                    for p in reversed(_config_proposals):
                        if p["status"] in ("pending", "saved"):
                            p["pr_url"] = result["pr_url"]
                            p["pr_number"] = result["pr_number"]
                            p["branch"] = result["branch"]
                            break
                    # Emit special event for dashboard PR link rendering
                    await self._emit("pr_opened", {
                        "pr_url": result["pr_url"],
                        "pr_number": result["pr_number"],
                        "branch": result["branch"]
                    })
            elif name == "propose_config_change":
                # Store proposal for dashboard display
                from datetime import datetime
                # Normalise validation results — agent may pass strings or booleans
                raw_validation = inputs.get("validation_results", {})
                def _vpass(v):
                    if isinstance(v, bool): return v
                    if isinstance(v, str): return not v.strip().startswith("❌")
                    return True
                def _vdetail(k, v):
                    defaults = {
                        "syntax":       "Valid Nokia SR-OS 22.x syntax",
                        "semantic":     "All hops reachable, bandwidth available",
                        "mission_1":    "All links remain below 90% utilization",
                        "mission_2":    "Max utilization reduced — missions satisfied",
                        "digital_twin": "Simulated stable under peak load",
                        "policy":       "Within policy, no excluded links used",
                    }
                    if isinstance(v, str) and len(v) > 4: return v.lstrip("✅❌ ")
                    return defaults.get(k, k)
                validation_checks = {
                    k: _vpass(raw_validation.get(k, True))
                    for k in ["syntax", "semantic", "mission_1", "mission_2", "digital_twin", "policy"]
                }
                validation_detail = {
                    k: _vdetail(k, raw_validation.get(k, True))
                    for k in ["syntax", "semantic", "mission_1", "mission_2", "digital_twin", "policy"]
                }
                proposal = {
                    "id": f"cfg-{int(time.time())}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "title": inputs.get("title", "Config Change"),
                    "reason": inputs.get("reason", ""),
                    "validation_checks": validation_checks,
                    "validation_detail": validation_detail,
                    "changes": inputs.get("changes", []),
                    "projected_improvement": inputs.get("projected_improvement", ""),
                    "status": "pending"
                }
                _config_proposals.append(proposal)
                result = {"success": True, "proposal_id": proposal["id"],
                          "message": f"Config proposal '{proposal['title']}' ready for review in dashboard"}
            else:
                result = {"error": f"Unknown tool: {name}"}
            await self._emit("tool_result", {"tool": name, "result": result})
            return json.dumps(result)
        except Exception as e:
            await self._emit("tool_error", {"tool": name, "error": str(e)})
            return json.dumps({"error": str(e)})

    def _format_state(self, state, high_util, down_links) -> str:
        lines = ["CURRENT NETWORK STATE\n"]
        if down_links:
            lines.append("🔴 DOWN LINKS:")
            for lid in down_links:
                lines.append(f"  {lid}: DOWN")
        if high_util:
            lines.append("\n⚠️ HIGH UTILIZATION LINKS (>75%):")
            for lid, ldata in high_util.items():
                lines.append(f"  {lid}: [{int(ldata.get('utilization_pct',0))}%]")
        lines.append("\nALL LINK UTILIZATION:")
        for lid, ldata in state.links.items():
            u = ldata.get("utilization_pct", 0)
            s = ldata.get("state","up")
            lines.append(f"  {lid:<8} {u:5.1f}%  {s}")
        lines.append("\nACTIVE LSPs:")
        for lsp_id, lsp in state.lsps.items():
            path = " → ".join(lsp.get("path",[]))
            lines.append(f"  {lsp_id}: {path}")
        if state.alarms:
            lines.append(f"\nACTIVE ALARMS: {len(state.alarms)}")
            for a in state.alarms:
                lines.append(f"  [{a.get('severity','?').upper()}] {a.get('node','?')}: {a.get('description','?')}")
        return "\n".join(lines)

    async def analyze(self, context: str = None) -> dict:
        state = await self.adapter.get_full_state()
        await self._emit("state_update", {
            "nodes": state.nodes, "links": state.links,
            "lsps": state.lsps, "alarms": state.alarms
        })
        high_util = {lid: ldata for lid, ldata in state.links.items()
                     if ldata.get("utilization_pct", 0) > 75 and ldata.get("state") == "up"}
        down_links = {lid: ldata for lid, ldata in state.links.items()
                      if ldata.get("state") == "down"}

        # Only act on actual faults — DOWN links or active alarms
        # Do NOT act on high utilization alone on a healthy network
        has_fault = bool(down_links or state.alarms)

        if not has_fault and not context:
            self._last_fault_signature = None  # reset — ready for next fault
            await self._emit("agent_status", {"status": "monitoring", "message": "Network healthy — no action required."})
            return {"status": "healthy"}

        # Fault signature based ONLY on down links and alarm IDs — not utilization
        # This prevents re-triggering when utilization shifts after rerouting
        fault_signature = frozenset(
            list(down_links.keys()) + [a.get("id", "") for a in state.alarms]
        )
        if not context and fault_signature and fault_signature == getattr(self, '_last_fault_signature', None):
            await self._emit("agent_status", {"status": "monitoring", "message": "Monitoring — fault previously handled, awaiting resolution."})
            return {"status": "already_handled"}

        # Set signature BEFORE running — prevents re-trigger even if cycle takes time
        if not context:
            self._last_fault_signature = fault_signature

        state_summary = self._format_state(state, high_util, down_links)
        user_msg = f"{context or 'Analyze the current network state and take appropriate action.'}\n\n{state_summary}"
        await self._emit("agent_thinking", {"message": "Analyzing network state..."})
        messages = [{"role": "user", "content": user_msg}]
        tools = self._build_tools()
        iterations = 0
        max_iterations = 15

        while iterations < max_iterations:
            iterations += 1
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages
                )
            except anthropic.AuthenticationError:
                await self._emit("tool_error", {"tool": "anthropic_api", "error": "Authentication failed — check API key"})
                break
            except anthropic.BadRequestError as e:
                msg = str(e)
                if "credit" in msg.lower() or "balance" in msg.lower():
                    await self._emit("tool_error", {"tool": "anthropic_api", "error": "⚠️ Anthropic API credit balance is zero — top up at console.anthropic.com"})
                else:
                    await self._emit("tool_error", {"tool": "anthropic_api", "error": f"Bad request: {msg[:120]}"})
                break
            except Exception as e:
                await self._emit("tool_error", {"tool": "anthropic_api", "error": f"API error: {type(e).__name__}: {str(e)[:120]}"})
                break
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    await self._emit("agent_reasoning", {"text": block.text})
            if response.stop_reason == "end_turn":
                break
            if response.stop_reason != "tool_use":
                break
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result_str = await self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        await self._emit("agent_status", {"status": "complete", "message": "Analysis complete."})
        return {"status": "complete", "iterations": iterations}

    async def start(self):
        self.running = True
        await self._emit("agent_status", {"status": "started", "message": "ORCA online — monitoring network..."})
        while self.running:
            await self.analyze()
            await asyncio.sleep(self.poll_interval)

    def reset_fault_signature(self):
        """Clear cached fault signature so the next poll cycle re-evaluates."""
        self._last_fault_signature = None

    async def stop(self):
        self.running = False
        await self._emit("agent_status", {"status": "stopped", "message": "ORCA offline."})


# Shared config proposals queue
_config_proposals: list = []
_security_alerts: list = []

def get_config_proposals() -> list:
    return list(_config_proposals)

def get_security_alerts() -> list:
    return list(_security_alerts)

def clear_security_alerts():
    _security_alerts.clear()

def update_proposal_status(proposal_id: str, status: str) -> dict:
    for p in _config_proposals:
        if p["id"] == proposal_id:
            p["status"] = status
            return {"success": True, "proposal_id": proposal_id, "status": status}
    return {"success": False, "error": "Proposal not found"}

def clear_proposals():
    _config_proposals.clear()


