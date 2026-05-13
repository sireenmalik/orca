"""
ORCA API Server — FastAPI backend with WebSocket streaming
"""
import asyncio, json, os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent.te_agent import ORCAAgent, get_config_proposals, update_proposal_status, clear_proposals, get_security_alerts, clear_security_alerts
from agent.adapter import ContainerlabAdapter
from agent.notifications import send_email, build_tac_email, get_pending_emails, clear_emails
from agent import v2_proposals
from agent import scenarios as v2_scenarios
from agent import churn_state
from agent import v2_emails
from agent import customer_intents
from agent import churn_correlator
from agent import intent_distiller
from agent import policy_index

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
    # Load any ratified policy intents into the PolicyIndex on startup
    # so match_policy_intent works the moment the container is healthy.
    # No-op on first-ever deploy (intents/policy/ doesn't exist yet).
    try:
        policy_index.reload()
    except Exception as _e:
        print(f"[startup] policy_index.reload() failed: "
              f"{type(_e).__name__}: {_e}", flush=True)
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

# ── Customer intents (Demo #3 — drill-in) ─────────────────────────────────────
@app.get("/api/customers")
async def list_customers():
    """All customer fixtures, list-of-dicts. Source: intents/customers/*.yaml
    today; will be a TMF921 / BSS-API fetch in production."""
    return {"customers": customer_intents.get_customers()}

@app.get("/api/customers/{customer_id}")
async def get_customer(customer_id: str):
    c = customer_intents.get_by_id(customer_id)
    if not c:
        return {"error": "not found", "customer_id": customer_id}
    return c

@app.post("/api/customers/{customer_id}/correlate")
async def correlate_customer(customer_id: str):
    """Trigger Nemotron (low_effort) to produce a per-customer churn-risk
    causal explanation. The agent reads the customer's profile + the live
    network telemetry on their service underlay and returns a structured
    JSON: churn_pct, risk_drivers, recommended_action, executive_summary."""
    return await churn_correlator.correlate(customer_id, agent)

@app.get("/api/state")
async def get_state():
    state = await adapter.get_full_state()
    return {
        "nodes": state.nodes, "links": state.links,
        "lsps": state.lsps, "alarms": state.alarms,
        # v2 demo additions — RAN/UPF topology layer
        "slices":         state.slices,
        "sessions":       state.sessions,
        "qer_state":      state.qer_state,
        "slice_metrics":  state.slice_metrics,
        "link_flags":     state.link_flags,
        "playing_scenario": v2_scenarios.is_playing(),
    }

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

def _reset_to_baseline():
    """Factory-reset the adapter. Used by /api/demo/reset and as the
    baseline-restore callback passed into v2_scenarios.inject()/stop()."""
    global adapter
    adapter = ContainerlabAdapter()
    agent.adapter = adapter

@app.post("/api/demo/reset")
async def reset_network():
    # Halt any in-flight scenario playback first so new demo takes start clean.
    await v2_scenarios.stop(manager.broadcast, reset_baseline_if_requested=False,
                             reset_baseline=_reset_to_baseline)
    _reset_to_baseline()
    v2_proposals.clear_proposals()      # v2 demo proposals (the scripted Acts)
    clear_proposals()                    # AGENT's _config_proposals (real propose_config_change)
    clear_security_alerts()              # AGENT's _security_alerts
    agent.reset_fault_signature()        # AGENT's dedup state + proposal_approved flag
    # Also clear the cycle artifact pointers so the next cycle's emails
    # don't carry stale PR/episode URLs into a fresh fault.
    agent._cycle_pr_url = ""
    agent._cycle_pr_number = None
    agent._cycle_episode_url = ""
    clear_emails()                       # agent email queue (notifications.py)
    v2_emails.clear_all()                # v2 outbox — drafts + sent
    customer_intents.clear_impacted()    # customers return to baseline (healthy)
    churn_state.reset()
    await manager.broadcast({
        "type":      "customer_state_changed",
        "timestamp": datetime.utcnow().isoformat(),
        "data":      {"impacted": [], "reason": "demo_reset"},
    })
    await manager.broadcast({
        "type": "churn_updated",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {"phase": "baseline"},
    })
    await manager.broadcast({
        "type": "emails_cleared",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {},
    })
    asyncio.create_task(_broadcast_state())
    return {"status": "reset", "message": "Network reset to baseline"}

# ── v2 scenario playback endpoints ────────────────────────────────────────────
@app.get("/api/scenarios")
async def list_scenarios():
    return {"scenarios": v2_scenarios.list_scenarios(), "playing": v2_scenarios.is_playing()}

@app.post("/api/scenarios/{scenario_id}/inject")
async def inject_scenario(scenario_id: str):
    # Every scenario inject starts FULLY clean — same wipe as ↻ Reset Demo:
    # all proposals (v2 + agent), all emails, all alarms, all security
    # alerts, all churn state, all cycle artifact pointers, customer
    # impact flags, agent dedup signature. Each Act runs entirely
    # independent of the previous one. No compound-fault simulation today.
    await reset_network()
    # After reset_network the module-level ``adapter`` global has been
    # rebound to a fresh instance. Read it now (post-reset) so we hand
    # the live one to v2_scenarios.inject.
    return await v2_scenarios.inject(
        scenario_id,
        broadcast=manager.broadcast,
        adapter=adapter,
        reset_baseline=_reset_to_baseline,
        agent=agent,
    )

@app.post("/api/scenarios/stop")
async def stop_scenarios():
    return await v2_scenarios.stop(
        broadcast=manager.broadcast,
        reset_baseline_if_requested=False,
        reset_baseline=_reset_to_baseline,
    )

@app.post("/api/scenarios/reset")
async def reset_scenarios():
    r = await v2_scenarios.stop(
        broadcast=manager.broadcast,
        reset_baseline_if_requested=True,
        reset_baseline=_reset_to_baseline,
    )
    v2_proposals.clear_proposals()
    clear_emails()
    v2_emails.clear_all()
    churn_state.reset()
    await manager.broadcast({
        "type": "churn_updated",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {"phase": "baseline"},
    })
    await manager.broadcast({
        "type": "emails_cleared",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {},
    })
    asyncio.create_task(_broadcast_state())
    return {**r, "state": "baseline"}

# ── v2 Email Outbox ─────────────────────────────────────────────────────────
# Distinct from v1 /api/emails (which backs baseline tests). Act 1 approval
# drafts an internal NOC notification; Act 2 drafts an external TAC handoff.
# See agent/v2_emails.py for templates + store.

class V2EmailAction(BaseModel):
    comment: str = ""

# ── Shape adapters for unified UI ────────────────────────────────────────────
# The v2 dashboard tabs (Email Outbox, Config Proposals) read /api/v2/emails
# and /api/proposals respectively. On the NIMO branch the agent (Nemotron or
# Sonnet) writes to the agent-native lists exposed at /api/emails and
# /api/config-proposals — different shapes, populated by real LLM tool calls
# rather than scripted demo Acts. To make those visible without a frontend
# rewrite we transform agent records into the v2 shape on the way out and
# union them with whatever the v2 lists hold.

def _agent_email_to_v2(e: dict) -> dict:
    to = e.get("to", "")
    return {
        "id":         e.get("id", ""),
        "type":       "internal_ops",
        "to":         [to] if isinstance(to, str) and to else (to if isinstance(to, list) else []),
        "subject":    e.get("subject", ""),
        "body":       e.get("body", ""),
        "status":     "sent",
        "tag":        "agent",
        "created_at": e.get("timestamp"),
    }

def _agent_proposal_to_v2(p: dict) -> dict:
    vc = p.get("validation_checks", {}) or {}
    vd = p.get("validation_detail", {}) or {}
    gates = [
        {
            "name":   k.replace("_", " ").title(),
            "status": "pass" if (vc.get(k, True) if isinstance(vc.get(k, True), bool) else True) else "fail",
            "detail": vd.get(k, "") if isinstance(vd.get(k, ""), str) else "",
        }
        for k in ("syntax", "semantic", "mission_1", "mission_2", "digital_twin", "policy")
    ]
    devices, device_diffs, device_configs = [], {}, {}
    seen = set()
    for ch in p.get("changes", []) or []:
        d = ch.get("device") or ch.get("node") or ch.get("router") or "unknown"
        if d not in seen:
            seen.add(d)
            devices.append({"id": d, "label": f"{d} · {ch.get('type','change')}", "note": ch.get("type", "change")})
            device_diffs[d]   = []
            device_configs[d] = ""
        if ch.get("diff_summary"):
            device_diffs[d].append({"type": "context", "line": ch["diff_summary"]})
        if ch.get("current_config"):
            for ln in str(ch["current_config"]).splitlines():
                device_diffs[d].append({"type": "remove", "line": ln})
        if ch.get("new_config"):
            for ln in str(ch["new_config"]).splitlines():
                device_diffs[d].append({"type": "add", "line": ln})
            device_configs[d] += ch["new_config"] + "\n"
    return {
        "id":                p.get("id", ""),
        "title":             p.get("title", "(untitled)"),
        "summary":           (p.get("title") or "")[:120],
        "reason":            p.get("reason", ""),
        "projected_impact":  p.get("projected_improvement", ""),
        "status":            p.get("status", "pending"),
        "validation_gates":  gates,
        "devices":           devices,
        "device_diffs":      device_diffs,
        "device_configs":    device_configs,
        "diff":              (device_diffs.get(devices[0]["id"], []) if devices else []),
        "created_at":        p.get("timestamp"),
        "pr_url":            p.get("pr_url"),
        "pr_number":         p.get("pr_number"),
        "_origin":           "agent",
    }

@app.get("/api/v2/emails")
async def v2_list_emails():
    base  = list(v2_emails.get_emails())
    agent_emails = [_agent_email_to_v2(e) for e in (get_pending_emails() or [])]
    return {"emails": base + agent_emails}

@app.post("/api/v2/emails/{email_id}/send")
async def v2_send_email(email_id: str, body: V2EmailAction = V2EmailAction()):
    e = v2_emails.mark_sent(email_id)
    if not e:
        return {"error": "not found or not in draft state"}
    to_s = ", ".join(e.get("to", []))
    subj = (e.get("subject", "") or "")[:80]
    await manager.broadcast({
        "type":      "agent_status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "status":  "email_sent",
            "message": f"✉ {to_s} email dispatched · subject: {subj}",
        },
    })
    await manager.broadcast({
        "type": "email_updated", "timestamp": datetime.utcnow().isoformat(),
        "data": {"id": email_id, "status": "sent"},
    })
    return e

# ── v2 security teaser (Act 3) ────────────────────────────────────────────────
# One lightweight endpoint that broadcasts an alert-type reasoning log entry.
# Distinct from the v1 /api/demo/inject-rogue-config flow (which creates
# alerts, evidence archives, revert proposals) — Act 3 is a teaser, not a
# full security scenario.

@app.post("/api/v2/security/inject-event")
async def v2_inject_security_event():
    """Emit one alert-type scenario_log entry. Used for the Act 3 teaser."""
    content = (
        "Unauthorized gNMI config change attempt detected · target: PE-02 "
        "· source IP: 10.0.3.44 · invalid certificate · change blocked · "
        "connection terminated"
    )
    detail = {
        "source_ip":          "10.0.3.44",
        "target_device":      "PE-02",
        "attempted_change":   "gNMI SET on interface configuration",
        "certificate_status": "invalid (self-signed, not in trust store)",
        "action_taken":       "connection terminated, change blocked",
        "logged_to":          "SIEM (placeholder tag)",
    }
    await manager.broadcast({
        "type":      "scenario_log",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "seq":           -99,
            "subtype":       "alert",
            "content":       content,
            "is_conclusion": False,
            "scenario_id":   "act3-security-teaser",
            "detail":        detail,
        },
    })
    return {"status": "emitted", "content": content}

@app.post("/api/v2/emails/{email_id}/discard")
async def v2_discard_email(email_id: str, body: V2EmailAction = V2EmailAction()):
    # Grab the subject before deletion for the log entry
    all_emails = v2_emails.get_emails()
    existing = next((e for e in all_emails if e.get("id") == email_id), None)
    subj = ((existing or {}).get("subject", "") or "")[:80]
    ok = v2_emails.discard(email_id)
    if not ok:
        return {"error": "not found"}
    await manager.broadcast({
        "type":      "agent_status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "status":  "email_discarded",
            "message": f"✗ Email draft discarded by operator · {subj}",
        },
    })
    await manager.broadcast({
        "type": "email_updated", "timestamp": datetime.utcnow().isoformat(),
        "data": {"id": email_id, "status": "discarded"},
    })
    return {"status": "discarded", "id": email_id}

# ── v2 Churn Forecast ─────────────────────────────────────────────────────────
# Dashboard-flavor state; not a real churn model. Act 1 approval flips
# slice-A from 423 → 14 at-risk via trigger_slice_a_recovery (hooked in
# v2_proposals._deploy).

@app.get("/api/churn")
async def get_churn():
    return churn_state.get_state()

@app.post("/api/churn/reset")
async def reset_churn_tab():
    churn_state.reset()
    await manager.broadcast({
        "type": "churn_updated",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {"phase": "baseline"},
    })
    return {"status": "baseline"}

# ── v2 Config Proposals workflow ──────────────────────────────────────────────
# New endpoints at /api/proposals (distinct from the v1 /api/config-proposals
# store wired to the baseline test suite). See agent/v2_proposals.py.

class V2ProposalCreate(BaseModel):
    title: str = ""
    reason: str = ""
    projected_impact: str = ""
    diff: list = []
    validation_gates: list = []
    triggering_incident_id: str = ""

class V2ProposalAction(BaseModel):
    comment: str = ""

@app.get("/api/proposals")
async def v2_list_proposals():
    base  = list(v2_proposals.get_proposals())
    agent_props = [_agent_proposal_to_v2(p) for p in (get_config_proposals() or [])]
    return {"proposals": base + agent_props}

@app.post("/api/proposals")
async def v2_create_proposal(req: V2ProposalCreate):
    p = v2_proposals.create_proposal(req.dict())
    await manager.broadcast({
        "type": "agent_status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "status":  "proposal_created",
            "message": f"📝 {p['id']} created — {p['title']}",
        },
    })
    return p

@app.delete("/api/proposals")
async def v2_clear_proposals():
    v2_proposals.clear_proposals()
    return {"status": "cleared"}

def _is_agent_proposal_id(proposal_id: str) -> bool:
    return any(str(p.get("id")) == str(proposal_id) for p in (get_config_proposals() or []))

@app.post("/api/proposals/{proposal_id}/approve")
async def v2_approve_proposal(proposal_id: str, body: V2ProposalAction = V2ProposalAction()):
    # Dispatch by id origin so the v2 dashboard's single approve button
    # correctly routes agent-created proposals through the agent's
    # stream_approval pipeline (which opens a real PR + writes the episode).
    if _is_agent_proposal_id(proposal_id):
        return await approve_proposal(proposal_id, ProposalAction(comment=body.comment))
    return await v2_proposals.approve_proposal(proposal_id, manager.broadcast)

@app.post("/api/proposals/{proposal_id}/reject")
async def v2_reject_proposal(proposal_id: str, body: V2ProposalAction = V2ProposalAction()):
    if _is_agent_proposal_id(proposal_id):
        return await reject_proposal(proposal_id, ProposalAction(comment=body.comment))
    return await v2_proposals.reject_proposal(proposal_id, manager.broadcast, body.comment)

class V2ProposalSave(BaseModel):
    comment: Optional[str] = None
    reason: Optional[str] = None
    device_configs: Optional[dict] = None
    diff: Optional[list] = None

@app.post("/api/proposals/{proposal_id}/save")
async def v2_save_proposal(proposal_id: str, body: V2ProposalSave):
    result = v2_proposals.save_edits(proposal_id, body.dict(exclude_none=True))
    if "error" in result:
        return result
    await manager.broadcast({
        "type":      "agent_status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "status":  "proposal_saved",
            "message": f"📝 Proposal {proposal_id} reviewed and committed by operator · diff updated",
        },
    })
    return result

async def _broadcast_state():
    await asyncio.sleep(0.3)
    state = await adapter.get_full_state()
    await manager.broadcast({
        "type": "state_update", "timestamp": datetime.utcnow().isoformat(),
        "data": {"nodes": state.nodes, "links": state.links, "lsps": state.lsps,
                 "alarms": state.alarms, "slices": state.slices, "sessions": state.sessions,
                 "qer_state": state.qer_state, "slice_metrics": state.slice_metrics,
                 "link_flags": state.link_flags,
                 "playing_scenario": v2_scenarios.is_playing()},
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
    result = adapter.inject_rogue_config("PE-01")
    rogue_changes = result.get("changes", [])

    # Add alarm to network state
    from agent.adapter import Alarm
    alarm = Alarm(
        id=f"sec-alarm-{int(_time.time())}",
        severity="critical", node="PE-01",
        description="Security: Config drift detected on PE-01 — gNMI running config diverges from Git baseline"
    )
    adapter._alarms.append(alarm)

    # Pre-populate _security_alerts immediately — don't wait for ORCA analyze
    from agent.te_agent import _security_alerts
    provisional_alert = {
        "id": f"sec-{int(_time.time())}",
        "timestamp": datetime.utcnow().isoformat(),
        "node": "PE-01",
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
    return {"success": True, "node": "PE-01", "changes": rogue_changes,
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


_deploying_proposals: set = set()

@app.post("/api/config-proposals/{proposal_id}/approved")
@app.post("/api/config-proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, body: ProposalAction = ProposalAction()):
    # Idempotency guard: dashboard posts to both /approved and /approve and
    # occasional retries / double-clicks would otherwise spawn stream_approval
    # twice — which creates duplicate PRs and duplicate "Config Deployed"
    # emails. First write wins; later calls just return the current status.
    if proposal_id in _deploying_proposals:
        return {"success": True, "proposal_id": proposal_id, "status": "already_deploying"}
    _deploying_proposals.add(proposal_id)

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
    trigger_link = proposal.get("trigger_link", "PE-01-PE-04")
    trigger_type = proposal.get("trigger_type", "link_failure")
    trigger_desc = proposal.get("reason", f"{trigger_type} on {trigger_link}")
    lsps_affected = proposal.get("lsps_affected", ["lsp-customer-a", "lsp-customer-b"])
    actions_taken = proposal.get("actions_taken", [
        "rerouted lsp-customer-a via PE-01-PE-02-P-01-PE-04",
        "rerouted lsp-customer-b via P-02-P-01-PE-02",
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
        f"After {trigger_link} failure: prefer reroute via PE-01-PE-02-P-01-PE-04 for lsp-customer-a")

    # ── Distiller-targeted resolution data ──
    # Derived deterministically from (a) the scenario context the agent
    # snapshotted onto the proposal at propose_config_change time, and
    # (b) the customer YAMLs. No LLM rewording in this path.
    impacted_ids = (proposal.get("impacted_customers")
                    or sorted(customer_intents.get_impacted())
                    or [])
    arr_at_risk_usd = 0
    for cid in impacted_ids:
        rec = customer_intents.get_by_id(cid) or {}
        arr_at_risk_usd += int(rec.get("arr_usd", 0) or 0)
    diagnosis_text = proposal.get("scenario_description", "") or trigger_desc
    scenario_id_val = proposal.get("scenario_id", "")

    # Fix: agent sends 'device' key, not 'node'
    routers = list({ch.get("device", ch.get("node", ch.get("router", "PE-01"))) for ch in changes}) or ["PE-01"]
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
                # ── Distiller-targeted fields (deterministic) ──
                "scenario_id":          scenario_id_val,
                "diagnosis":            diagnosis_text,
                "outcome":              "save_via_config_change",
                "nokia_config_change":  True,
                "human_involvement":    True,   # operator clicked Approve to reach this branch
                "customers":            impacted_ids,
                "affected_customer_count": len(impacted_ids),
                "arr_at_risk":          arr_at_risk_usd,
                "saved_arr":            arr_at_risk_usd,  # save resolved cleanly
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
            episode_yaml = ep_data.get("content", "") or ""
        except Exception:
            episode_url = f"https://github.com/sireenmalik/orca/tree/main/skills/past/episodes/{ep_month}/"
            episode_id  = ""
            episode_yaml = ""

        # ── 4b. Fire the Intent Distiller in the background.
        # Non-critical learning loop — never blocks the operator-facing
        # post-deployment NOC email (step 5 below). distill_episode_safe
        # cannot raise; the create_task wrapper guards against schedule
        # failure. policy_intent_proposed ws event broadcast on success.
        if episode_yaml:
            try:
                from agent.intent_distiller import distill_episode_safe as _distill
                async def _bg():
                    intent = await _distill(episode_yaml)
                    if intent:
                        try:
                            await manager.broadcast({
                                "type":      "policy_intent_proposed",
                                "timestamp": datetime.utcnow().isoformat(),
                                "data": {
                                    "intent_id":      intent.get("intent_id", ""),
                                    "title":          intent.get("title", ""),
                                    "action_type":    (intent.get("action") or {}).get("type", ""),
                                    "confidence":     intent.get("confidence", 0),
                                    "source_episode": episode_id,
                                    "github_url":     intent.get("github_url", ""),
                                },
                            })
                        except Exception as _be:
                            print(f"[distiller] broadcast failed: {_be}",
                                  flush=True)
                asyncio.create_task(_bg())
            except Exception as _e:
                print(f"[distiller-trigger] schedule failed: "
                      f"{type(_e).__name__}: {_e}", flush=True)

        # ── 5. Send NOC email with PR + episode links — same Issue/Resolution
        # template the agent uses, plus a validation-tests block and the
        # post-deployment status. Both URLs are clickable.
        ops_email = os.getenv("OPS_EMAIL", "sireenmalik@gmail.com")
        ts_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        validation_lines = "\n".join(
            f"  {'✅' if v else '❌'} {k.replace('_', ' ').title():14}— {validation_detail.get(k,'')}"
            for k, v in validation.items()
        )
        change_lines = "\n".join(
            f"  • {ch.get('device', ch.get('node', '?'))}: {ch.get('diff_summary', ch.get('type','change'))}"
            for ch in changes
        ) or "  (see PR diff)"

        issue_text = trigger_desc or "see proposal reason"
        resolution_text = (
            f"Operator approved proposal {proposal.get('id','?')}. "
            f"Config committed to branch {branch} (commit {commit_sha[:8] if commit_sha else '—'}) "
            f"and deployed via NETCONF to {routers_str}. "
            f"{proposal.get('projected_improvement', 'See episode for projected outcome.')}"
        )
        post_status = (
            f"Config committed and deployed. {len(changes)} change(s) applied across "
            f"{routers_str}. Deployment validated via the digital twin against all "
            f"six gates (see below)."
        )

        email_body = (
            f"1. Issue: {issue_text}\n\n"
            f"2. Resolution Proposed: {resolution_text}\n\n"
            f"3. Validation Tests (digital twin):\n{validation_lines}\n\n"
            f"4. Status After Deployment: {post_status}\n\n"
            f"Config Changes:\n{change_lines}\n\n"
            f"─── LINKS ────────────────────────────────────────\n"
            f"Config PR:   {pr_url or '(see GitHub)'}\n"
            f"Episode:     {episode_url}\n"
            f"Branch:      {branch}\n"
            f"Commit:      {commit_sha or '(see PR)'}\n"
            f"──────────────────────────────────────────────────\n\n"
            f"{ts_str} | by ORCA"
        )

        from agent.notifications import send_email
        send_email(
            to=ops_email,
            subject=f"✅ ORCA Config Deployed — {commit_title} | PR #{pr_number}",
            body=email_body
        )

        # If this was a security revert, mark the linked alert as remediated
        # so the Security tab stops showing it as "active". The proposal may
        # come from two paths: raise_security_alert (carries alert_id + the
        # security flag) or propose_config_change with a security-themed
        # title (doesn't). Handle both — prefer alert_id; fall back to the
        # most recent active alert on any router in the changes list.
        title_lc = (proposal.get("title", "") or "").lower()
        looks_security = (proposal.get("security")
                          or "security" in title_lc
                          or "revert" in title_lc
                          or proposal.get("trigger_type") == "security_violation")
        if looks_security:
            from agent.te_agent import _security_alerts
            alert_id = proposal.get("alert_id")
            remediated_alert = None
            target_nodes = {ch.get("device") or ch.get("node") or ch.get("router")
                            for ch in changes} - {None}
            for a in _security_alerts:
                matches_id   = alert_id and a.get("id") == alert_id
                matches_node = (not alert_id) and a.get("node") in target_nodes \
                               and a.get("status") not in ("remediated", "resolved")
                if matches_id or matches_node:
                    a["status"] = "remediated"
                    a["remediated_at"] = datetime.utcnow().isoformat()
                    a["remediation_pr_url"] = pr_url
                    a["remediation_pr_number"] = pr_number
                    remediated_alert = a
                    if matches_id:
                        break  # exact match — stop
            if remediated_alert:
                await manager.broadcast({
                    "type": "security_alert",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {"alert": remediated_alert},
                })

        await manager.broadcast({
            "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
            "data": {"status": "complete",
                     "message": f"✅ Incident closed — PR #{pr_number} | Episode {episode_id} | Config deployed to {routers_str}"}
        })

        # The save: clear the under-fault marker so the impacted customers
        # return to baseline (healthy) on the dashboard. This is the "save"
        # animating in the Customer Portfolio + Churn Risk donut.
        customer_intents.clear_impacted()
        await manager.broadcast({
            "type":      "customer_state_changed",
            "timestamp": datetime.utcnow().isoformat(),
            "data":      {"impacted": [], "reason": "config_deployed"},
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

# ── Policy Library ────────────────────────────────────────────────────────────
# Closed-loop policy learning surface. Pending intents are produced by
# the Intent Distiller after each resolution; the operator ratifies
# (Approve), edits (Edit), or discards (Reject) them in the Policy
# Library tab. Approve moves the pending YAML to intents/policy/<id>.yaml
# on main (token-auth bot commit, no GPG signing per project rule); the
# in-memory PolicyIndex reloads, and the next matching fault short-
# circuits the LLM reasoning loop (L5 closed loop).

class PolicyEdit(BaseModel):
    yaml: str = ""

class PolicyReject(BaseModel):
    reason: str = ""


def _gh_get_pending_listing() -> list:
    """List filenames in intents/policy/pending/ on main via GitHub API."""
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/intents/policy/pending?ref=main")
    import urllib.request as _ur, urllib.error as _ue
    req = _ur.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        **({"Authorization": f"token {token}"} if token else {}),
    })
    try:
        with _ur.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data if isinstance(data, list) else []
    except _ue.HTTPError as e:
        if e.code == 404:
            return []
        return []
    except Exception:
        return []


def _gh_get_raw(path: str) -> str:
    """Fetch file content from GitHub on main. Returns text or empty string."""
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/{path}?ref=main")
    import urllib.request as _ur
    req = _ur.Request(url, headers={
        "Accept": "application/vnd.github.raw",
        **({"Authorization": f"token {token}"} if token else {}),
    })
    try:
        with _ur.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return ""


def _gh_get_sha(path: str) -> str:
    """File SHA on main (needed for PUT/DELETE update calls)."""
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/{path}?ref=main")
    import urllib.request as _ur
    req = _ur.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        **({"Authorization": f"token {token}"} if token else {}),
    })
    try:
        with _ur.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("sha", "") if isinstance(data, dict) else ""
    except Exception:
        return ""


def _gh_put_file(path: str, content: str, message: str) -> bool:
    """PUT file to main with token-auth (create or update)."""
    import urllib.request as _ur, base64 as _b64
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    if not token:
        return False
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/{path}")
    payload = {"message": message,
               "content": _b64.b64encode(content.encode("utf-8")).decode("ascii"),
               "branch":  "main"}
    sha = _gh_get_sha(path)
    if sha:
        payload["sha"] = sha
    req = _ur.Request(url, data=json.dumps(payload).encode("utf-8"),
                      method="PUT", headers={
                          "Authorization": f"token {token}",
                          "Accept":        "application/vnd.github.v3+json",
                          "Content-Type":  "application/json",
                      })
    try:
        with _ur.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return bool(data.get("content"))
    except Exception as e:
        print(f"[policy-api] put {path} failed: {type(e).__name__}: {e}",
              flush=True)
        return False


def _gh_delete_file(path: str, message: str) -> bool:
    """DELETE file from main (the file's sha is required by GitHub API)."""
    import urllib.request as _ur
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    if not token:
        return False
    sha = _gh_get_sha(path)
    if not sha:
        return False
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/{path}")
    payload = {"message": message, "sha": sha, "branch": "main"}
    req = _ur.Request(url, data=json.dumps(payload).encode("utf-8"),
                      method="DELETE", headers={
                          "Authorization": f"token {token}",
                          "Accept":        "application/vnd.github.v3+json",
                          "Content-Type":  "application/json",
                      })
    try:
        with _ur.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[policy-api] delete {path} failed: {type(e).__name__}: {e}",
              flush=True)
        return False


def _parse_intent_yaml(text: str) -> dict:
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(text or "")
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


@app.get("/api/policy/pending")
async def list_pending_policy():
    """Pending policy intents — in-memory list (Distiller writes here on
    success) AND the durable GitHub copy at intents/policy/pending/. The
    two are kept in lockstep but the API returns the GitHub-side state
    so a container restart doesn't drop pending items the operator
    hasn't acted on yet."""
    out = []
    seen_ids = set()

    # GitHub-side (durable record)
    for entry in _gh_get_pending_listing():
        if entry.get("type") != "file":
            continue
        name = entry.get("name", "")
        if not name.endswith(".yaml"):
            continue
        body = _gh_get_raw(entry["path"])
        doc  = _parse_intent_yaml(body)
        if doc.get("intent_id"):
            doc["github_url"] = entry.get("html_url", "")
            doc["yaml"]       = body
            out.append(doc)
            seen_ids.add(doc["intent_id"])

    # Distiller's in-memory list (fresh proposals that may not yet have
    # round-tripped through GitHub on a slow connection)
    for doc in intent_distiller.get_pending_intents():
        if doc.get("intent_id") and doc["intent_id"] not in seen_ids:
            out.append(doc)
    out.sort(key=lambda d: d.get("proposed_at", ""), reverse=True)
    return {"pending": out}


@app.get("/api/policy/ratified")
async def list_ratified_policy():
    """Ratified policy intents currently active in the match index.
    Source of truth is intents/policy/ on main; the cache is refreshed
    on each call so freshly approved intents appear immediately."""
    policy_index.reload()
    out = []
    for doc in policy_index.get_ratified_intents():
        repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
        repo_name  = os.getenv("GITHUB_REPO",  "orca")
        intent_id  = doc.get("intent_id", "")
        doc = dict(doc)
        doc["github_url"] = (
            f"https://github.com/{repo_owner}/{repo_name}/blob/main/"
            f"intents/policy/{intent_id}.yaml"
        )
        out.append(doc)
    out.sort(key=lambda d: d.get("ratified_at", d.get("proposed_at", "")),
             reverse=True)
    return {"ratified": out}


@app.post("/api/policy/approve/{intent_id}")
async def approve_policy(intent_id: str):
    """Ratify a pending intent: write intents/policy/<id>.yaml on main,
    delete intents/policy/pending/<id>.yaml, drop from in-memory pending
    list, reload PolicyIndex. Broadcasts policy_intent_ratified so the
    dashboard refreshes both columns of the Policy Library tab."""
    pending_path = f"intents/policy/pending/{intent_id}.yaml"
    ratified_path = f"intents/policy/{intent_id}.yaml"
    body = _gh_get_raw(pending_path)
    if not body:
        # Fall back to in-memory copy in case GitHub fetch failed
        pending = intent_distiller.get_pending_intents()
        match_doc = next((p for p in pending
                          if p.get("intent_id") == intent_id), None)
        if not match_doc:
            return {"success": False, "error": "intent not found"}
        try:
            import yaml as _yaml
            body = _yaml.safe_dump(match_doc, sort_keys=False,
                                   default_flow_style=False)
        except Exception:
            return {"success": False, "error": "yaml dump failed"}

    # Stamp ratified_at + bot identity, append to body
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(body) or {}
        doc["ratified_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        doc["ratified_by"] = "orca-operator"
        body = _yaml.safe_dump(doc, sort_keys=False,
                               default_flow_style=False)
    except Exception:
        pass

    if not _gh_put_file(ratified_path, body,
                        f"policy: ratify {intent_id}"):
        return {"success": False, "error": "ratified write failed"}
    _gh_delete_file(pending_path,
                    f"policy: clear pending {intent_id} (ratified)")
    intent_distiller.pop_pending_intent(intent_id)
    count = policy_index.reload()

    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    gh_url = (f"https://github.com/{repo_owner}/{repo_name}/blob/main/"
              f"{ratified_path}")
    await manager.broadcast({
        "type":      "policy_intent_ratified",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "intent_id":   intent_id,
            "github_url":  gh_url,
            "active_count": count,
        },
    })
    return {"success": True, "intent_id": intent_id,
            "github_url": gh_url, "active_ratified_count": count}


@app.post("/api/policy/reject/{intent_id}")
async def reject_policy(intent_id: str, body: PolicyReject = PolicyReject()):
    """Reject a pending intent: move pending/<id>.yaml -> archive/<id>.yaml
    with the operator's reason appended. No PR."""
    pending_path = f"intents/policy/pending/{intent_id}.yaml"
    archive_path = f"intents/policy/archive/{intent_id}.yaml"
    yaml_body = _gh_get_raw(pending_path)
    if not yaml_body:
        # in-memory fallback
        pending = intent_distiller.get_pending_intents()
        m = next((p for p in pending if p.get("intent_id") == intent_id), None)
        if not m:
            return {"success": False, "error": "intent not found"}
        try:
            import yaml as _yaml
            yaml_body = _yaml.safe_dump(m, sort_keys=False,
                                        default_flow_style=False)
        except Exception:
            return {"success": False, "error": "yaml dump failed"}

    annotated = (yaml_body.rstrip()
                 + f"\nrejected_at: \"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}\""
                 + f"\nrejected_by: \"orca-operator\""
                 + f"\nrejection_reason: {json.dumps(body.reason or 'no reason given')}\n")
    if not _gh_put_file(archive_path, annotated,
                        f"policy: archive {intent_id} (rejected)"):
        return {"success": False, "error": "archive write failed"}
    _gh_delete_file(pending_path, f"policy: clear pending {intent_id} (rejected)")
    intent_distiller.pop_pending_intent(intent_id)
    return {"success": True, "intent_id": intent_id,
            "archive_path": archive_path}


@app.post("/api/policy/edit/{intent_id}")
async def edit_policy(intent_id: str, edit: PolicyEdit):
    """Save edited YAML back to intents/policy/pending/<id>.yaml. No
    ratification — operator still has to click Approve afterwards."""
    if not edit.yaml.strip():
        return {"success": False, "error": "empty yaml"}
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(edit.yaml)
        if not isinstance(doc, dict) or doc.get("intent_id") != intent_id:
            return {"success": False,
                    "error": "yaml must parse to dict with matching intent_id"}
    except Exception as e:
        return {"success": False, "error": f"yaml parse failed: {e}"}
    pending_path = f"intents/policy/pending/{intent_id}.yaml"
    if not _gh_put_file(pending_path, edit.yaml,
                        f"policy: operator edit {intent_id}"):
        return {"success": False, "error": "edit write failed"}
    # Refresh in-memory copy too
    intent_distiller.pop_pending_intent(intent_id)
    intent_distiller._pending_intents.append(doc)
    return {"success": True, "intent_id": intent_id}


@app.post("/api/policy/reload")
async def reload_policy_index():
    """Force re-scan of intents/policy/ on main. Useful after a manual
    git operation outside the API."""
    count = policy_index.reload()
    return {"success": True, "active_ratified_count": count}


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





