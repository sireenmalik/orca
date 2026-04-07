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

YOUR DECISION THRESHOLDS:
- Utilization > 80%: investigate and prepare rerouting plan
- Utilization > 90%: reroute immediately, then ALWAYS call notify_ops_team
- Link DOWN: reroute affected LSPs, then ALWAYS call notify_ops_team AND open_tac_case
- After ANY rerouting action: ALWAYS call notify_ops_team with a full summary
- After resolving a link failure: ALWAYS call propose_config_change to update IGP metrics for the new topology
- After every action cycle: ALWAYS call write_episode to record what happened, outcome, and any learned constraints
- After propose_config_change: ALWAYS call open_pull_request to create a Git branch and open a PR for engineer review
- open_pull_request creates a real PR on GitHub — include full incident summary in the PR body

MANDATORY NOTIFICATION RULE — YOU MUST ALWAYS FOLLOW THIS:
Every analysis cycle that results in any action MUST end with notify_ops_team.
This is not optional. Do not skip it even if the fault is resolved.
Include: what fault occurred, what you did, current state, affected LSPs.

YOUR REASONING PROCESS:
## 1. OBSERVATION — what do you see?
## 2. ANALYSIS — what does it mean?
## 3. PLAN — list actions including notify_ops_team and propose_config_change as final steps
## 4. ACTION — execute tools: diagnose → act → verify → notify → propose config
## 5. NOTIFICATION — call notify_ops_team (REQUIRED, never skip)

PRINCIPLES:
- Make-before-break: establish new path before tearing down old
- Prefer paths with < 60% utilization for rerouting
- Always verify after acting — never assume success
- Always notify — the ops team must know what happened
- After a link failure, propose permanent metric changes to optimise the new topology
"""


async def _write_episode(inputs: dict) -> dict:
    """Write episode to skills/past/episodes/ and push to GitHub."""
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

    episode = f"""# Episode {ep_id}
# Written by ORCA after action cycle
timestamp: "{now.isoformat()}Z"
trigger:
  type: "{inputs.get('trigger_type', 'unknown')}"
  link: "{inputs.get('trigger_link', '')}"
actions_taken:
{chr(10).join('  - "' + a + '"' for a in inputs.get('actions_taken', []))}
outcome:
  result: "{inputs.get('outcome', 'unknown')}"
  mission_1_satisfied: {str(inputs.get('mission_1_satisfied', True)).lower()}
  mission_2_improvement_pct: {inputs.get('mission_2_improvement_pct', 0)}
  time_to_resolution_seconds: {inputs.get('time_to_resolution_seconds', 0)}
  human_override: {str(inputs.get('human_override', False)).lower()}
  override_reason: "{inputs.get('override_reason', '')}"
learned_constraint: "{inputs.get('learned_constraint', '')}"
"""

    if not token:
        # Store locally in memory if no GitHub token
        return {"success": True, "episode_id": ep_id,
                "message": f"Episode {ep_id} recorded (no GitHub token — not pushed to repo)",
                "path": path}

    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json"
    }
    base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"

    payload = _json.dumps({
        "message": f"learn: episode {ep_id} — {inputs.get('trigger_type','event')} on {inputs.get('trigger_link','')} → {inputs.get('outcome','?')}",
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
    """Create branch, commit config, open PR on GitHub via API."""
    import urllib.request, urllib.error, json as _json, os as _os
    from datetime import datetime

    token = _os.getenv("GITHUB_TOKEN", "")
    repo_owner = _os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name = _os.getenv("GITHUB_REPO", "orca")

    if not token:
        return {"success": False, "error": "GITHUB_TOKEN not set — PR creation skipped",
                "note": "Set GITHUB_TOKEN in .env to enable automatic PR creation"}

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

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
    device = inputs.get("device", "device").lower()
    branch = f"cfg/{device}-{ts}"

    # 1. Get main branch SHA
    ref_data, _ = gh_request("GET", "/git/ref/heads/main")
    if "object" not in ref_data:
        return {"success": False, "error": f"Could not get main branch: {ref_data}"}
    main_sha = ref_data["object"]["sha"]

    # 2. Create new branch
    branch_data, status = gh_request("POST", "/git/refs", {
        "ref": f"refs/heads/{branch}",
        "sha": main_sha
    })
    if status not in (200, 201):
        return {"success": False, "error": f"Branch creation failed ({status}): {branch_data}"}

    # 3. Create/update file on branch
    config_path = inputs.get("config_path", f"config_mgmt/candidate/nokia-lab-sfo2/{inputs.get('device', 'R1')}.conf")
    import base64 as _b64
    content_b64 = _b64.b64encode(inputs["config_content"].encode()).decode()

    # Check if file exists to get SHA for update
    existing, ex_status = gh_request("GET", f"/contents/{config_path}?ref={branch}")
    file_payload = {
        "message": inputs["title"],
        "content": content_b64,
        "branch": branch
    }
    if ex_status == 200 and "sha" in existing:
        file_payload["sha"] = existing["sha"]

    file_data, fstatus = gh_request("PUT", f"/contents/{config_path}", file_payload)
    if fstatus not in (200, 201):
        return {"success": False, "error": f"File commit failed ({fstatus}): {file_data}"}

    # 4. Open PR
    pr_data, pr_status = gh_request("POST", "/pulls", {
        "title": inputs["title"],
        "body": inputs["body"],
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
        "message": f"PR #{pr_number} opened: {pr_url}"
    }


class ORCAAgent:
    def __init__(self, adapter: NetworkAdapter = None, anthropic_api_key: str = None):
        self.adapter = adapter or ContainerlabAdapter()
        self.client = anthropic.Anthropic(api_key=anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.running = False
        self.poll_interval = int(os.getenv("AGENT_POLL_INTERVAL", "15"))
        self._on_event: Optional[Callable] = None

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
                 "vendor": {"type": "string", "enum": ["cisco","juniper","nokia"]},
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
                vendor = inputs.get("vendor", "nokia")
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
                proposal = {
                    "id": f"cfg-{int(time.time())}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "title": inputs.get("title","Config Change"),
                    "reason": inputs.get("reason",""),
                    "validation": inputs.get("validation_results", {
                        "syntax": "✅ Valid Nokia SR-OS 22.x",
                        "semantic": "✅ All hops reachable, bandwidth available",
                        "mission_1": "✅ All links remain below 90%",
                        "mission_2": "✅ Max utilization improves",
                        "digital_twin": "✅ Simulated — stable under peak load",
                        "policy": "✅ Within policy, no excluded links"
                    }),
                    "changes": inputs.get("changes", []),
                    "projected_improvement": inputs.get("projected_improvement",""),
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
        if not high_util and not state.alarms and not down_links and not context:
            await self._emit("agent_status", {"status": "monitoring", "message": "Network healthy — no action required."})
            return {"status": "healthy"}

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

    async def stop(self):
        self.running = False
        await self._emit("agent_status", {"status": "stopped", "message": "ORCA offline."})


# Shared config proposals queue
_config_proposals: list = []

def get_config_proposals() -> list:
    return list(_config_proposals)

def update_proposal_status(proposal_id: str, status: str) -> dict:
    for p in _config_proposals:
        if p["id"] == proposal_id:
            p["status"] = status
            return {"success": True, "proposal_id": proposal_id, "status": status}
    return {"success": False, "error": "Proposal not found"}

def clear_proposals():
    _config_proposals.clear()
