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
from agent.te_agent import ORCAAgent, get_config_proposals, update_proposal_status, clear_proposals
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

@app.post("/api/config-proposals/{proposal_id}/approved")
@app.post("/api/config-proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, body: ProposalAction = ProposalAction()):
    result = update_proposal_status(proposal_id, "approved")
    await manager.broadcast({
        "type": "agent_status", "timestamp": datetime.utcnow().isoformat(),
        "data": {"status": "config_pushed",
                 "message": f"✅ Config pushed via NETCONF{' — ' + body.comment if body.comment else ''}"}
    })
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
