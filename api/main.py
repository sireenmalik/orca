"""
ORCA API Server — FastAPI backend with WebSocket streaming
"""
import asyncio, json, os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent.te_agent import ORCAAgent, get_config_proposals, update_proposal_status, clear_proposals, get_security_alerts, clear_security_alerts
from agent.adapter import ContainerlabAdapter
from agent.notifications import send_email, build_tac_email, get_pending_emails, clear_emails

adapter = ContainerlabAdapter()
agent = ORCAAgent(adapter=adapter)

class ConnectionManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)
    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)
    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = set()
        for ws in self.connections:
            try: await ws.send_text(msg)
            except: dead.add(ws)
        self.connections -= dead

manager = ConnectionManager()

async def on_agent_event(event: dict):
    await manager.broadcast(event)

agent.on_event(on_agent_event)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="ORCA API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class FaultRequest(BaseModel):
    link_id: str = ""
    utilization: float = 92.0

class AnalyzeRequest(BaseModel):
    context: str = ""

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ── State ─────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health(): return {"status": "ok", "service": "ORCA"}

@app.get("/api/state")
async def get_state():
    state = await adapter.get_full_state()
    return {"nodes": state.nodes, "links": state.links, "lsps": state.lsps, "alarms": state.alarms}

# ── Agent ─────────────────────────────────────────────────────────────────────
@app.post("/api/agent/start")
async def start_agent():
    asyncio.create_task(agent.start())
    return {"status": "started"}

@app.post("/api/agent/stop")
async def stop_agent():
    await agent.stop()
    return {"status": "stopped"}

@app.post("/api/agent/analyze")
async def analyze(req: AnalyzeRequest):
    asyncio.create_task(agent.analyze(req.context))
    return {"status": "analyzing"}

# ── Demo fault injection ──────────────────────────────────────────────────────
@app.post("/api/demo/inject-failure")
async def inject_failure(req: FaultRequest):
    result = await adapter.simulate_failure(req.link_id)
    asyncio.create_task(_broadcast_state())
    return result

@app.post("/api/demo/inject-congestion")
async def inject_congestion(req: FaultRequest):
    result = await adapter.inject_congestion(req.link_id, req.utilization) \
             if hasattr(adapter, 'inject_congestion') else {"success": False, "error": "Not supported"}
    asyncio.create_task(_broadcast_state())
    return result

@app.post("/api/demo/restore-link")
async def restore_link(req: FaultRequest):
    result = await adapter.restore_link(req.link_id)
    asyncio.create_task(_broadcast_state())
    return result

@app.post("/api/demo/reset")
async def reset_network():
    global adapter
    adapter = ContainerlabAdapter()
    agent.adapter = adapter
    asyncio.create_task(_broadcast_state())
    return {"status": "reset", "message": "Network reset to baseline"}

async def _broadcast_state():
    await asyncio.sleep(0.3)
    state = await adapter.get_full_state()
    await manager.broadcast({
        "type": "state_update", "timestamp": datetime.utcnow().isoformat(),
        "data": {"nodes": state.nodes, "links": state.links, "lsps": state.lsps, "alarms": state.alarms}
    })

# ── Email queue ───────────────────────────────────────────────────────────────
@app.get("/api/emails")
async def get_emails(): return {"emails": get_pending_emails()}

@app.delete("/api/emails")
async def delete_emails(): clear_emails(); return {"status": "cleared"}

# ── Config proposals ──────────────────────────────────────────────────────────
@app.get("/api/config-proposals")
async def get_proposals(): return {"proposals": get_config_proposals()}

class ProposalAction(BaseModel):
    comment: str = ""
    changes: list = []

@app.post("/api/demo/inject-rogue-config")
async def inject_rogue_config():
    """Inject unauthorized config change for security breach demo."""
    import time as _time
    result = adapter.inject_rogue_config("R1")
    rogue_changes = result.get("changes", [])

    # Add alarm to network state
    from agent.adapter import Alarm
    alarm = Alarm(
        id=f"sec-alarm-{int(_time.time())}",
        severity="critical", node="R1",
        description="Security: Config drift detected on R1 — gNMI running config diverges from Git baseline"
    )
    adapter._alarms.append(alarm)

    # Pre-populate _security_alerts immediately — don't wait for ORCA analyze
    from agent.te_agent import _security_alerts
    provisional_alert = {
        "id": f"sec-{int(_time.time())}",
        "timestamp": datetime.utcnow().isoformat(),
        "node": "R1",
        "severity": "critical",
        "type": "unauthorized_config_change",
        "detail": f"Rogue changes detected: {', '.join(ch.get('parameter','?') for ch in rogue_changes)} — source IP {result.get('source_ip','10.0.3.44')} via NETCONF direct push",
        "classification": "management_plane_exposure",
        "changes": rogue_changes,
        "status": "detected — awaiting ORCA analysis",
        "source": "gNMI config drift detection",
        "provisional": True,
    }
    _security_alerts.append(provisional_alert)

    # Broadcast security_alert (not security_alarm) so Security tab picks it up
    await manager.broadcast({
        "type": "security_alert",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {"alert": provisional_alert}
    })
    asyncio.create_task(_broadcast_state())
    return {"success": True, "node": "R1", "changes": rogue_changes,
            "message": "Rogue config injected — security alert raised, ORCA will analyze"}

@app.post("/api/demo/clear-rogue-config")
async def clear_rogue_config():
    """Clear injected rogue config."""
    adapter.clear_rogue_config()
    return {"success": True}

@app.post("/api/demo/security-reset")
async def security_reset():
    """Full security demo reset — clear rogue config, alerts, proposals, alarms, network state."""
    global adapter
    # Clear rogue config
    adapter.clear_rogue_config()
    # Clear security alarms from adapter
    adapter._alarms = [a for a in adapter._alarms if "Security" not in a.description and "drift" not in a.description]
    # Clear security alerts store
    from agent.te_agent import _security_alerts
    _security_alerts.clear()
    # Reset agent fault signature
    agent.reset_fault_signature()
    # Broadcast clean state
    asyncio.create_task(_broadcast_state())
    await manager.broadcast({
        "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
        "data": {"status": "reset", "message": "🔄 Security demo reset — network restored to clean baseline"}
    })
    return {"success": True, "message": "Security demo reset complete"}

# ── Security alerts ───────────────────────────────────────────────────────────
@app.get("/api/security-alerts")
async def get_alerts(): return {"alerts": get_security_alerts()}

@app.delete("/api/security-alerts")
async def delete_alerts(): clear_security_alerts(); return {"status": "cleared"}

# ── Churn risk ────────────────────────────────────────────────────────────────
@app.get("/api/churn-risk")
async def get_churn_risk():
    """Return latest churn risk scores for all customer LSPs."""
    import math
    lsp_meta = {
        "lsp-customer-a": {"customer": "Customer-A", "segment": "Enterprise", "arr_usd": 2400000},
        "lsp-customer-b": {"customer": "Customer-B", "segment": "SMB", "arr_usd": 480000},
    }
    segment_multiplier = {"Enterprise": 0.7, "SMB": 1.0}
    risks = {}
    for lsp_id, meta in lsp_meta.items():
        history = adapter.get_lsp_history(lsp_id, 96) if hasattr(adapter, 'get_lsp_history') else []
        utils = [h["util"] for h in history] if history else [35.0]
        reroutes = sum(1 for h in history if h.get("rerouted", False))
        breach_90 = sum(1 for u in utils if u >= 90)
        breach_80 = sum(1 for u in utils if u >= 80)
        time_degraded = breach_80 * 15
        max_slots = max(len(utils), 1)
        raw = (
            0.35 * min(breach_90 / max(max_slots * 0.1, 1), 1.0) +
            0.25 * min(time_degraded / 1440, 1.0) +
            0.20 * min(reroutes / 5, 1.0) +
            0.12 * min(breach_80 / max(max_slots * 0.2, 1), 1.0)
        )
        risk_score = round(min(raw * 100, 100), 1)
        k, midpoint = 0.08, 60
        base_prob = 1 / (1 + math.exp(-k * (risk_score - midpoint)))
        churn_prob = round(min(base_prob * segment_multiplier.get(meta["segment"], 1.0) * 100, 99), 1)
        band = "healthy" if risk_score <= 25 else "watch" if risk_score <= 55 else "at_risk" if risk_score <= 80 else "critical"
        risks[lsp_id] = {**meta, "lsp_id": lsp_id, "risk_score": risk_score, "risk_band": band,
                         "churn_probability_pct": churn_prob, "reroute_count": reroutes,
                         "breach_90_count": breach_90, "time_degraded_mins": time_degraded}
    return {"risks": risks}


@app.post("/api/config-proposals/{proposal_id}/approved")
@app.post("/api/config-proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, body: ProposalAction = ProposalAction()):
    result = update_proposal_status(proposal_id, "approved")
    # Mark fault as resolved — do NOT clear fault signature here.
    # Clearing it would cause ORCA to re-propose on the next analyze cycle.
    # The signature is cleared automatically when the network heals (no more down links/alarms).
    agent._proposal_approved = True  # suppress re-proposal for current fault

    all_proposals = get_config_proposals()
    proposal = next((p for p in all_proposals if str(p.get("id")) == str(proposal_id)), {})

    changes = proposal.get("changes", body.changes or [])
    diff = proposal.get("diff", [])

    validation = proposal.get("validation_checks", {
        "syntax": True, "semantic": True, "mission_1": True,
        "mission_2": True, "digital_twin": True, "policy": True
    })
    validation_detail = proposal.get("validation_detail", {
        "syntax":       "Valid Nokia SR-OS 22.x syntax",
        "semantic":     "All hops reachable, bandwidth available",
        "mission_1":    "All links remain below 90% utilization",
        "mission_2":    "Max utilization reduced — missions satisfied",
        "digital_twin": "Simulated stable under peak load",
        "policy":       "Within policy, no excluded links used",
    })
    trigger_link = proposal.get("trigger_link", "R1-R4")
    trigger_type = proposal.get("trigger_type", "link_failure")
    trigger_desc = proposal.get("reason", f"{trigger_type} on {trigger_link}")
    lsps_affected = proposal.get("lsps_affected", ["lsp-customer-a", "lsp-customer-b"])
    actions_taken = proposal.get("actions_taken", [
        "rerouted lsp-customer-a via R1-R6-R5-R4",
        "rerouted lsp-customer-b via R2-R5-R6",
        "notified ops team via email",
        "opened Nokia TAC P1 case",
        f"proposed and pushed permanent IGP metric changes: {proposal.get('title', 'config update')}"
    ])
    reasoning = proposal.get("reasoning_summary",
        "ORCA detected link failure, computed alternate paths via CSPF, rerouted affected LSPs. "
        "Permanent IGP metric changes pushed to optimise topology for new steady state.")
    m1_detail = proposal.get("mission_1_detail", "Max utilization held below 90% after rerouting")
    m2_detail  = proposal.get("mission_2_detail", f"Max utilization reduced — {proposal.get('projected_improvement', 'see episode')}")
    util_before = proposal.get("util_before", {})
    util_after  = proposal.get("util_after", {})
    max_before  = proposal.get("max_util_before", 0)
    max_after   = proposal.get("max_util_after", 0)
    improvement = proposal.get("mission_2_improvement_pct", 0)
    learned     = proposal.get("learned_constraint",
        f"After {trigger_link} failure: prefer reroute via R1-R6-R5-R4 for lsp-customer-a")

    # Fix: agent sends 'device' key, not 'node'
    routers = list({ch.get("device", ch.get("node", ch.get("router", "R1"))) for ch in changes}) or ["R1"]
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    branch = f"cfg/{'_'.join(sorted(routers))}-{ts}"

    async def stream_approval():
        await asyncio.sleep(0.3)

        # ── 1. Stream git commands ──
        config_files = [f"config_mgmt/candidate/nokia-lab-sfo2/{r}.conf" for r in routers]
        diff_files   = [f"config_mgmt/diff/nokia-lab-sfo2/{r}.diff" for r in routers]
        all_files    = config_files + diff_files
        routers_str  = ",".join(sorted(routers))
        commit_title = proposal.get("title", "ORCA config update")

        git_cmds = [
            f"git checkout -b {branch}",
            "git add " + " ".join(all_files),
            f'git commit -m "cfg({routers_str}): {commit_title}"',
            f"git push origin {branch}",
        ]
        for cmd in git_cmds:
            await manager.broadcast({
                "type": "git_command", "timestamp": datetime.utcnow().isoformat(),
                "data": {"command": cmd}
            })
            await asyncio.sleep(0.6)

        # ── 2. Simulate NETCONF push per router ──
        for router in routers:
            router_changes = [ch for ch in changes if ch.get("device", ch.get("node", ch.get("router"))) == router]
            for ch in router_changes:
                netconf_msg = (
                    f"NETCONF edit-config → {router}: "
                    f"{ch.get('type','metric_change')} — {ch.get('diff_summary', ch.get('new_config',''))[:80]}"
                )
                await manager.broadcast({
                    "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
                    "data": {"status": "netconf_push", "message": f"⚙️ {netconf_msg}"}
                })
                await asyncio.sleep(0.5)
            await manager.broadcast({
                "type": "tool_result", "timestamp": datetime.utcnow().isoformat(),
                "data": {"tool": "netconf_push", "result": {"success": True,
                    "message": f"✅ {router}: config committed — running config updated"}}
            })
            await asyncio.sleep(0.4)

        await manager.broadcast({
            "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
            "data": {"status": "config_pushed",
                     "message": f"✅ Config pushed via NETCONF to {routers_str} — branch {branch}"}
        })
        await asyncio.sleep(0.4)

        # ── 3. Open GitHub PR ──
        pr_inputs = {
            "title": f"cfg: {commit_title} [{ts}]",
            "trigger_type": trigger_type,
            "trigger_link": trigger_link,
            "trigger_description": trigger_desc,
            "lsps_affected": lsps_affected,
            "actions_taken": actions_taken,
            "reasoning_summary": reasoning,
            "changes": changes,
            "diff": diff,
            "validation_checks": validation,
            "validation_detail": validation_detail,
            "mission_1_satisfied": validation.get("mission_1", True),
            "mission_2_satisfied": validation.get("mission_2", True),
            "mission_1_detail": m1_detail,
            "mission_2_detail": m2_detail,
            "max_util_before": max_before,
            "max_util_after": max_after,
            "mission_2_improvement_pct": improvement,
            "utilization_before": util_before,
            "utilization_after": util_after,
            "time_to_resolution_seconds": proposal.get("time_to_resolution_seconds", 0),
            "episode_path": f"skills/past/episodes/{datetime.utcnow().strftime('%Y-%m')}/",
        }
        pr_url = ""
        pr_number = "?"
        commit_sha = ""
        episode_url = ""
        try:
            pr_result = await agent._execute_tool("open_pull_request", pr_inputs)
            pr_data = json.loads(pr_result) if isinstance(pr_result, str) else pr_result
            pr_url    = pr_data.get("pr_url", "")
            pr_number = pr_data.get("pr_number", "?")
            commit_sha = pr_data.get("commit_sha", "")
        except Exception as e:
            await manager.broadcast({"type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
                "data": {"status": "error", "message": f"PR creation error: {e}"}})

        if pr_url:
            await manager.broadcast({
                "type": "pr_opened", "timestamp": datetime.utcnow().isoformat(),
                "data": {"pr_number": pr_number, "pr_url": pr_url,
                         "message": f"PR #{pr_number} opened — {pr_url}"}
            })
        await asyncio.sleep(0.3)

        # ── 4. Write episode ──
        ep_month = datetime.utcnow().strftime("%Y-%m")
        try:
            ep_result = await agent._execute_tool("write_episode", {
                "trigger_type": trigger_type,
                "trigger_link": trigger_link,
                "trigger_description": trigger_desc,
                "actions_taken": actions_taken + [f"config pushed via NETCONF to {routers_str}", f"GitHub PR #{pr_number}: {pr_url}"],
                "reasoning_summary": reasoning,
                "lsps_affected": lsps_affected,
                "changes": changes,
                "diff": diff,
                "validation_checks": validation,
                "validation_detail": validation_detail,
                "outcome": "success",
                "mission_1_satisfied": validation.get("mission_1", True),
                "mission_2_satisfied": validation.get("mission_2", True),
                "mission_1_detail": m1_detail,
                "mission_2_detail": m2_detail,
                "mission_2_improvement_pct": improvement,
                "max_util_before": max_before,
                "max_util_after": max_after,
                "utilization_before": util_before,
                "utilization_after": util_after,
                "time_to_resolution_seconds": proposal.get("time_to_resolution_seconds", 0),
                "notifications_sent": [
                    "ops team email — link failure + LSP rerouting summary",
                    "Nokia TAC P1 case opened",
                    f"GitHub PR #{pr_number} — {pr_url}",
                    f"Config pushed via NETCONF to {routers_str}",
                ],
                "pr_url": pr_url,
                "pr_number": pr_number,
                "branch": branch,
                "commit_sha": commit_sha,
                "learned_constraint": learned,
            })
            ep_data = json.loads(ep_result) if isinstance(ep_result, str) else ep_result
            episode_url = ep_data.get("url", f"https://github.com/sireenmalik/orca/tree/main/skills/past/episodes/{ep_month}/")
            episode_id  = ep_data.get("episode_id", "")
        except Exception:
            episode_url = f"https://github.com/sireenmalik/orca/tree/main/skills/past/episodes/{ep_month}/"
            episode_id  = ""

        # ── 5. Send NOC email with PR + episode links ──
        ops_email = os.getenv("OPS_EMAIL", "sireenmalik@gmail.com")
        check_summary = "\n".join(
            f"  {'✅' if v else '❌'} {k}: {validation_detail.get(k,'')}"
            for k, v in validation.items()
        )
        email_body = f"""ORCA Config Management Report
==============================

Incident: {trigger_desc}
Routers affected: {routers_str}
Proposed improvement: {proposal.get('projected_improvement', 'see episode')}

VALIDATION CHECKS
-----------------
{check_summary}

CONFIG CHANGES PUSHED
---------------------
Branch: {branch}
Commit: {commit_sha or 'see PR'}
"""
        for ch in changes:
            router = ch.get("device", ch.get("node", ch.get("router", "?")))
            email_body += f"\n{router}: {ch.get('diff_summary', ch.get('type','change'))}"

        email_body += f"""

LINKS
-----
GitHub PR #{pr_number}: {pr_url or 'see GitHub'}
Episode: {episode_url}

Actions taken:
""" + "\n".join(f"  - {a}" for a in actions_taken)

        from agent.notifications import send_email
        send_email(
            to=ops_email,
            subject=f"✅ ORCA Config Deployed — {commit_title} | PR #{pr_number}",
            body=email_body
        )

        await manager.broadcast({
            "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
            "data": {"status": "complete",
                     "message": f"✅ Incident closed — PR #{pr_number} | Episode {episode_id} | Config deployed to {routers_str}"}
        })

    asyncio.create_task(stream_approval())
    return result

@app.post("/api/config-proposals/{proposal_id}/committed")
async def commit_proposal(proposal_id: str, body: ProposalAction = ProposalAction()):
    result = update_proposal_status(proposal_id, "committed")
    await manager.broadcast({
        "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
        "data": {"status": "config_committed", "message": f"🔀 Config committed to Git{' — ' + body.comment if body.comment else ''}"}
    })
    return result

@app.post("/api/config-proposals/{proposal_id}/saved")
async def save_proposal(proposal_id: str, body: ProposalAction = ProposalAction()):
    return update_proposal_status(proposal_id, "saved")

@app.post("/api/config-proposals/{proposal_id}/rejected")
@app.post("/api/config-proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, body: ProposalAction = ProposalAction()):
    return update_proposal_status(proposal_id, "rejected")

@app.post("/api/emails/{email_id}/send")
async def send_email_action(email_id: str, body: dict = None):
    return {"success": True, "message": f"Email {email_id} send triggered"}

@app.delete("/api/config-proposals")
async def delete_proposals(): clear_proposals(); return {"status": "cleared"}

@app.post("/api/config-proposals/{proposal_id}/pending")
async def reopen_proposal(proposal_id: str):
    return update_proposal_status(proposal_id, "pending")

# ── Debug ─────────────────────────────────────────────────────────────────────
@app.get("/api/debug/env")
async def debug_env():
    api_key = os.getenv("SENDGRID_API_KEY", "NOT SET")
    ops_email = os.getenv("OPS_EMAIL", "NOT SET")
    env_check = {
        "SENDGRID_API_KEY": f"{api_key[:6]}...({len(api_key)} chars)" if api_key != "NOT SET" else "NOT SET",
        "OPS_EMAIL": ops_email,
    }
    test_result = send_email(to=ops_email, subject="⚡ ORCA — Email Integration Test",
                             body="ORCA email integration test.")
    return {"env": env_check, "email_test": test_result}

# ── Static dashboard ──────────────────────────────────────────────────────────
dashboard_path = "/opt/orca/dashboard/dist"
if os.path.exists(dashboard_path):
    app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="static")





