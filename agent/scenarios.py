"""
ORCA v2 demo — scripted scenario playback.

Two scenarios mirror the v2 demo script's Act 1 and Act 2:

    slice-a-qos-drift                — Act 1: slice-A QoS degradation on UPF-01
    transport-congestion-upf-innocent — Act 2: LSP-1 congestion, core innocent

Each scenario is a fully scripted pair of (reasoning log entries, state
mutations) played back on fixed delays. No LLM — everything here is
pre-composed so the demo's 7-minute budget is deterministic.

Playback broadcasts events over the WebSocket bus, which the Agent
Reasoning Log panel already listens on:

    {type: "scenario_started", data: {id, name, duration_seconds}}
    {type: "scenario_log",     data: {subtype, content, is_conclusion, seq}}
    {type: "scenario_complete",data: {id}}
    {type: "scenario_stopped", data: {id, reason}}

State mutations go through ``adapter.apply_scenario_patch(path, op, value)``
— a small dotted-path walker on ContainerlabAdapter. Each change triggers
a fresh ``state_update`` broadcast so the topology and KPI panels refresh
in lockstep with the reasoning log.

Interrupt semantics: if a second inject arrives while a scenario is
playing, the first is cancelled (CancelledError propagates through the
sleeps), the adapter is reset to baseline, and the second begins.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional


# ─── Scenario definitions ────────────────────────────────────────────────────

SCENARIOS = {
    # ═══════════════ ACT 1: Slice-A QoS degradation on UPF-01 ═══════════════
    "slice-a-qos-drift": {
        "id":                "slice-a-qos-drift",
        "name":              "Slice-A QoS degradation on UPF-01",
        "short_label":       "Act 1 — slice-A QoS",
        "description":       "Dual root cause: session skew + QER drift. ORCA detects pre-threshold, proposes atomic 2-change package.",
        "duration_seconds":  45,
        # State evolves from t=0 over ~45s. Each entry is an absolute
        # offset from scenario start (milliseconds). The playback engine
        # schedules them as independent tasks so a high-density state
        # sweep doesn't block the log stream.
        "state_changes": [
            # Session skew climbing 612 → 637 over 5s (5/sec), then holds.
            {"at_ms":  200, "target": "sessions.UPF-01.total",                "op": "set", "value": 617},
            {"at_ms":  200, "target": "sessions.UPF-01.by_slice.slice-A",     "op": "set", "value": 617},
            {"at_ms":  200, "target": "sessions.UPF-01.by_gnb.gNB-1",         "op": "set", "value": 617},
            {"at_ms": 1200, "target": "sessions.UPF-01.total",                "op": "set", "value": 622},
            {"at_ms": 1200, "target": "sessions.UPF-01.by_slice.slice-A",     "op": "set", "value": 622},
            {"at_ms": 1200, "target": "sessions.UPF-01.by_gnb.gNB-1",         "op": "set", "value": 622},
            {"at_ms": 2200, "target": "sessions.UPF-01.total",                "op": "set", "value": 627},
            {"at_ms": 2200, "target": "sessions.UPF-01.by_slice.slice-A",     "op": "set", "value": 627},
            {"at_ms": 2200, "target": "sessions.UPF-01.by_gnb.gNB-1",         "op": "set", "value": 627},
            {"at_ms": 3200, "target": "sessions.UPF-01.total",                "op": "set", "value": 632},
            {"at_ms": 3200, "target": "sessions.UPF-01.by_slice.slice-A",     "op": "set", "value": 632},
            {"at_ms": 3200, "target": "sessions.UPF-01.by_gnb.gNB-1",         "op": "set", "value": 632},
            {"at_ms": 4200, "target": "sessions.UPF-01.total",                "op": "set", "value": 637},
            {"at_ms": 4200, "target": "sessions.UPF-01.by_slice.slice-A",     "op": "set", "value": 637},
            {"at_ms": 4200, "target": "sessions.UPF-01.by_gnb.gNB-1",         "op": "set", "value": 637},
            # QER drift flag flips at t=3s
            {"at_ms": 3000, "target": "qer_state.UPF-01.slice-A", "op": "set",
             "value": {"intent_gbr_mbps": 50, "enforced_mbps": 32, "status": "drifted"}},
            # p99 latency climb 11 → 13 over 8s starting at t=5s
            {"at_ms":  5000, "target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 11.2},
            {"at_ms":  6500, "target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 11.6},
            {"at_ms":  8000, "target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 12.1},
            {"at_ms":  9500, "target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 12.5},
            {"at_ms": 11000, "target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 12.8},
            {"at_ms": 13000, "target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 13.0},
            # Info alarm at t=10s (pre-threshold — not critical)
            {"at_ms": 10000, "target": "alarms", "op": "append",
             "value": {
                "id": "info-slice-a-p99-trend",
                "severity": "info",
                "node": "UPF-01",
                "description": "Slice-A p99 trend slope suggests SLA breach within 4 minutes",
                "source": "ORCA",
             }},
        ],
        "reasoning_log_entries": [
            {"delay_ms": 200,  "type": "detect",   "content": "gNMI telemetry update received from UPF-01. Slice-A p99 N3 latency: 11.2ms → climbing."},
            {"delay_ms": 150,  "type": "detect",   "content": "Trend slope analysis over 90s window: p99 extrapolated breach of 15ms SLA in ~4 minutes."},
            {"delay_ms": 300,  "type": "detect",   "content": "Pre-threshold detection engaged. Initiating diagnosis before SLA breach."},
            {"delay_ms": 200,  "type": "analyze",  "content": "Checking UPF-01 session distribution for slice-A..."},
            {"delay_ms": 400,  "type": "analyze",  "content": "Session table: UPF-01 carrying 637 slice-A sessions · UPF-02 carrying 0. Expected distribution: balanced. Observed: full skew to UPF-01."},
            {"delay_ms": 150,  "type": "analyze",  "content": "Checking UPF-01 QER state for slice-A priority class..."},
            {"delay_ms": 400,  "type": "analyze",  "content": "QER table: slice-A priority class intent = GBR 50 Mbps · enforced = 32 Mbps. Drift detected: -36% from intent."},
            {"delay_ms": 200,  "type": "correlate","content": "Correlating: session skew concentrates slice-A load on UPF-01. QER drift under-enforces slice-A priority on that same UPF. Combined effect explains p99 climb."},
            {"delay_ms": 2500, "type": "conclude", "is_conclusion": True,
             "content": "Diagnosis complete. Dual root cause: load-balancer session skew + QER priority drift. Single-cause fix will not hold."},
            {"delay_ms": 400,  "type": "decide",   "content": "Composing atomic config package. Change 1: QER update on UPF-01 restoring slice-A GBR to 50 Mbps. Change 2: PFCP session modification, rebalance 180 slice-A high-bandwidth sessions to UPF-02."},
            {"delay_ms": 300,  "type": "decide",   "content": "Running validation gates: syntax ✓ semantic ✓ mission utilization ✓ mission slice SLA ✓ digital twin (60s traffic simulation) ✓ policy ✓"},
            {"delay_ms": 500,  "type": "conclude", "is_conclusion": True,
             "content": "All six validation gates pass. Proposal ready for human approval."},
        ],
    },

    # ══════════════ ACT 2: Transport congestion, UPF-02 innocent ═══════════
    "transport-congestion-upf-innocent": {
        "id":                "transport-congestion-upf-innocent",
        "name":              "Transport congestion on LSP-1, UPF-02 innocent",
        "short_label":       "Act 2 — transport congestion",
        "description":       "LSP-1 path PE-01↔P-02 at 93%. ORCA clears UPF/SMF/AMF then pivots to transport — Nokia core is innocent.",
        "duration_seconds":  60,
        "state_changes": [
            # Link PE-01 ↔ P-02 jumps to 93% with microburst flag at t=0
            {"at_ms":    0, "target": "link_util.PE-01-P-02",             "op": "set", "value": 93.0},
            {"at_ms":    0, "target": "link_flags.PE-01-P-02.microbursts","op": "set", "value": True},
            # Propagate onto LSP-1 utilization (a derived display marker)
            {"at_ms": 2000, "target": "metrics.LSP-1.util_pct",           "op": "set", "value": 93.0},
            # Slice-A p99 on UPF-01 climbs because LSP-1 carries it
            {"at_ms":  4000, "target": "metrics.UPF-01.slice_A.p99_ms",   "op": "set", "value": 9.4},
            {"at_ms":  5500, "target": "metrics.UPF-01.slice_A.p99_ms",   "op": "set", "value": 10.8},
            {"at_ms":  7000, "target": "metrics.UPF-01.slice_A.p99_ms",   "op": "set", "value": 12.1},
            {"at_ms":  8500, "target": "metrics.UPF-01.slice_A.p99_ms",   "op": "set", "value": 13.2},
            {"at_ms": 10000, "target": "metrics.UPF-01.slice_A.p99_ms",   "op": "set", "value": 14.0},
            # Warning alarm at t=8s
            {"at_ms": 8000, "target": "alarms", "op": "append",
             "value": {
                "id": "warn-slice-a-p99-rising",
                "severity": "warning",
                "node": "UPF-01",
                "description": "Slice-A p99 latency rising on UPF-01",
                "source": "monitoring",
             }},
        ],
        "reasoning_log_entries": [
            {"delay_ms": 200,  "type": "detect",   "content": "gNMI telemetry update: slice-A p99 N3 latency climbing on UPF-01. Current 12.8ms, trending toward 15ms SLA."},
            {"delay_ms": 200,  "type": "detect",   "content": "Checking UPF-01 local state..."},
            {"delay_ms": 300,  "type": "analyze",  "content": "UPF-01 CPU: 34%. Memory pressure: nominal. PFCP association to SMF: healthy. QER state: matches intent."},
            {"delay_ms": 200,  "type": "analyze",  "content": "UPF-01 local resources not the cause. Expanding scope."},
            {"delay_ms": 300,  "type": "analyze",  "content": "Checking SMF keepalive and AMF session count..."},
            {"delay_ms": 300,  "type": "analyze",  "content": "SMF healthy. AMF session count nominal. Core signaling plane clean."},
            {"delay_ms": 400,  "type": "analyze",  "content": "Expanding scope to transport telemetry for LSP-1 path..."},
            {"delay_ms": 500,  "type": "analyze",  "content": "LSP-1 path: PE-01 → P-02 → PE-03. Link PE-01 ↔ P-02 at 93% utilization. Microbursts detected in last 60s."},
            {"delay_ms": 200,  "type": "correlate","content": "Correlating: slice-A traffic from gNB-1 traverses LSP-1. LSP-1 congestion on PE-01 ↔ P-02 directly explains p99 climb at UPF-01."},
            {"delay_ms": 2500, "type": "conclude", "is_conclusion": True,
             "content": "Diagnosis complete. Nokia core is innocent. Root cause is transport-layer congestion on PE-01 ↔ P-02, upstream of UPF-01."},
            {"delay_ms": 400,  "type": "decide",   "content": "ORCA has read-only access to transport. No direct fix available at transport layer. Composing two parallel responses."},
            {"delay_ms": 300,  "type": "decide",   "content": "Response 1 (Nokia-domain workaround): migrate slice-A sessions off LSP-1's congested path. PFCP session modification to re-anchor sessions via alternate path."},
            {"delay_ms": 300,  "type": "decide",   "content": "Response 2 (transport handoff): drafting TAC email to operator transport team with evidence package and three suggested transport-side resolutions."},
            {"delay_ms": 500,  "type": "conclude", "is_conclusion": True,
             "content": "Workaround proposal validated (6/6 gates). TAC email drafted. Both ready for human review."},
        ],
    },
}


# ─── Proposal templates ──────────────────────────────────────────────────────
#
# Each scenario's conclusion triggers auto-creation of one proposal from
# these templates. The workflow chassis (agent/v2_proposals.py) handles
# id generation, validation-gate normalisation, and PR creation on approve.
# Post-approval scenario-specific recovery log entries are emitted from
# v2_proposals._deploy() when ``triggering_scenario_id`` is set.

SCENARIO_PROPOSAL_TEMPLATES = {
    "slice-a-qos-drift": {
        "title": "Slice-A QoS protection on UPF-01",
        "reason": (
            "Dual root cause on slice-A: (1) load-balancer session skew concentrates the "
            "enterprise cohort on UPF-01 with UPF-02 carrying zero slice-A sessions, "
            "(2) QER enforcement on UPF-01 priority class has drifted -36% from intent "
            "(50 → 32 Mbps GBR). Combined effect: p99 N3 latency climbing 11.2ms → trending "
            "toward 15ms SLA breach in ~4 minutes. Single-cause fix will not hold — both "
            "changes must ship atomically."
        ),
        "projected_impact": (
            "p99 N3 latency returns to ~9ms · slice-A SLA breach risk eliminated for 842 "
            "enterprise subscribers · $2.4M enterprise ARR cohort protected"
        ),
        "diff": [
            {"type": "context", "line": "upf-01:"},
            {"type": "context", "line": "  qer_profiles:"},
            {"type": "context", "line": "    slice-a-priority:"},
            {"type": "context", "line": "      intent_gbr_mbps: 50"},
            {"type": "remove",  "line": "      enforced_mbps: 32       # DRIFT -36% from intent"},
            {"type": "add",     "line": "      enforced_mbps: 50       # restored to intent"},
            {"type": "add",     "line": "      enforcement_mode: strict"},
            {"type": "context", "line": "  pfcp_sessions:"},
            {"type": "context", "line": "    slice-A:"},
            {"type": "remove",  "line": "      high_bw_count: 637      # concentration on UPF-01"},
            {"type": "add",     "line": "      high_bw_count: 457      # 180 sessions migrated to UPF-02"},
            {"type": "context", "line": "upf-02:"},
            {"type": "context", "line": "  pfcp_sessions:"},
            {"type": "context", "line": "    slice-A:"},
            {"type": "remove",  "line": "      high_bw_count: 0"},
            {"type": "add",     "line": "      high_bw_count: 180      # balanced tail-distribution"},
        ],
        "validation_gates": [
            {"name": "Syntax",                "status": "pass",
             "detail": "Candidate YAML schema-valid · SR Linux / CNF parser clean"},
            {"name": "Semantic",              "status": "pass",
             "detail": "All referenced UPFs, slices, and PFCP session groups exist"},
            {"name": "Mission · utilization", "status": "pass",
             "detail": "Post-change link utilization stays under 90% on all paths"},
            {"name": "Mission · slice SLA",   "status": "pass",
             "detail": "Slice-A p99 projected 8.9ms, well within 15ms SLA threshold"},
            {"name": "Digital twin",          "status": "pass",
             "detail": "60s traffic replay against candidate: no SLA breach, no session drop"},
            {"name": "Policy",                "status": "pass",
             "detail": "Change stays within approved QER enforcement policy envelope"},
        ],
        "triggering_incident_id": "slice-a-qos-drift",
    },

    "transport-congestion-upf-innocent": {
        "title": "Slice-A session migration off congested LSP-1",
        "reason": (
            "Transport layer congestion on PE-01 ↔ P-02 (93% utilization, microbursts) is "
            "upstream of UPF-01 and causing slice-A p99 N3 latency to climb toward SLA "
            "breach. ORCA has read-only access to transport — no direct fix available at "
            "the MPLS layer. Nokia-domain workaround: re-anchor slice-A sessions via an "
            "alternate PFCP path that bypasses the congested LSP-1. Parallel action: TAC "
            "email drafted to operator transport team with evidence + three suggested "
            "transport-side resolutions."
        ),
        "projected_impact": (
            "Slice-A traffic bypasses PE-01 ↔ P-02 congestion · p99 N3 latency recovers "
            "to ~9ms · enterprise SLA preserved until operator resolves upstream transport "
            "congestion · Nokia core impact fully contained"
        ),
        "diff": [
            {"type": "context", "line": "upf-01:"},
            {"type": "context", "line": "  pfcp_sessions:"},
            {"type": "context", "line": "    slice-A:"},
            {"type": "context", "line": "      anchor_path: via-LSP-1"},
            {"type": "remove",  "line": "      high_bw_count: 612      # on congested LSP-1 path"},
            {"type": "add",     "line": "      high_bw_count: 432      # 180 sessions re-anchored"},
            {"type": "context", "line": "  session_migration_override:"},
            {"type": "add",     "line": "    slice-A:"},
            {"type": "add",     "line": "      target_count: 180"},
            {"type": "add",     "line": "      alternate_path: via-LSP-2"},
            {"type": "add",     "line": "      rationale: 'LSP-1 PE-01↔P-02 at 93% — bypass'"},
            {"type": "add",     "line": "      ttl_hours: 6           # auto-revert when transport resolved"},
            {"type": "context", "line": "notifications:"},
            {"type": "add",     "line": "  tac_email:"},
            {"type": "add",     "line": "    vendor: operator_transport_team"},
            {"type": "add",     "line": "    subject: 'Slice-A N3 impact · LSP-1 PE-01↔P-02 congestion'"},
        ],
        "validation_gates": [
            {"name": "Syntax",                "status": "pass",
             "detail": "Candidate YAML schema-valid · PFCP override block syntax clean"},
            {"name": "Semantic",              "status": "pass",
             "detail": "Alternate path via LSP-2 is up and has headroom"},
            {"name": "Mission · utilization", "status": "pass",
             "detail": "Post-migration: LSP-2 peak util projected 61%, still under 90%"},
            {"name": "Mission · slice SLA",   "status": "pass",
             "detail": "Slice-A p99 projected 9.1ms · slice-B path unaffected"},
            {"name": "Digital twin",          "status": "pass",
             "detail": "60s replay under current transport congestion: slice-A recovers, no collateral"},
            {"name": "Policy",                "status": "pass",
             "detail": "Session-migration override is TTL-bounded · auto-reverts in 6h"},
        ],
        "triggering_incident_id": "transport-congestion-upf-innocent",
    },
}


# Scenario-specific post-deploy recovery log entries, streamed sequentially
# (200-400ms between) after /api/proposals/{id}/approve completes the
# deploy simulation. Rendered with type="recovered" for green styling.
SCENARIO_RECOVERY_ENTRIES = {
    "slice-a-qos-drift": [
        {"delay_ms": 200, "content": "QER update on UPF-01 committed · slice-A priority class now enforcing GBR 50 Mbps"},
        {"delay_ms": 300, "content": "PFCP session modification batch complete · 180 slice-A sessions re-anchored to UPF-02 over 6.2 seconds · user-plane continuity preserved"},
        {"delay_ms": 400, "content": "Slice-A p99 N3 latency recovered: 13.1 ms → 8.9 ms · SLA headroom restored"},
    ],
    "transport-congestion-upf-innocent": [
        # Note: the old "TAC email dispatched" line used to live here
        # (Prompt 4). Removed in Prompt 6 — the email is now a draft in
        # the Outbox, not a fait accompli. The "email drafted" system
        # log comes from v2_emails on deploy hook instead.
        {"delay_ms": 200, "content": "PFCP session modification batch complete · 180 slice-A sessions re-routed via alternate path · bypassing congested LSP-1"},
        {"delay_ms": 400, "content": "Nokia-domain impact contained · slice-A p99 N3 latency recovered"},
    ],
}


# ─── Playback engine ─────────────────────────────────────────────────────────
#
# A single module-level task holds the current playback. New inject cancels
# the old task; reset does the same and also restores adapter baseline.

_current_task: Optional[asyncio.Task] = None
_current_id:   Optional[str] = None


def list_scenarios() -> list:
    return [
        {
            "id":               s["id"],
            "name":             s["name"],
            "short_label":      s["short_label"],
            "description":      s["description"],
            "duration_seconds": s["duration_seconds"],
        }
        for s in SCENARIOS.values()
    ]


def is_playing() -> Optional[str]:
    """Returns the id of the currently-playing scenario, or None."""
    if _current_task and not _current_task.done():
        return _current_id
    return None


async def _play(scenario: dict, broadcast, adapter) -> None:
    """Stream log entries + schedule state patches. Clears _current_id
    on completion (natural or cancelled) via the outer try/finally so
    the 'Playing: Act X' indicator always drops."""
    global _current_id
    # Signal start
    await broadcast({
        "type":      "scenario_started",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "id":               scenario["id"],
            "name":             scenario["name"],
            "short_label":      scenario["short_label"],
            "duration_seconds": scenario["duration_seconds"],
        },
    })

    # Schedule state changes as independent tasks keyed on absolute offset.
    async def _apply_later(patch):
        await asyncio.sleep(patch["at_ms"] / 1000.0)
        try:
            adapter.apply_scenario_patch(patch["target"], patch["op"], patch["value"])
        except Exception:
            pass  # best-effort in demo; a bad patch shouldn't kill the scenario
        # After every patch, broadcast a fresh state_update so the UI
        # KPIs + topology colours move in lockstep with the log.
        try:
            state = await adapter.get_full_state()
            await broadcast({
                "type": "state_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "nodes":            state.nodes,    "links":         state.links,
                    "lsps":             state.lsps,     "alarms":        state.alarms,
                    "slices":           getattr(state, "slices",        {}),
                    "sessions":         getattr(state, "sessions",      {}),
                    "qer_state":        getattr(state, "qer_state",     {}),
                    "slice_metrics":    getattr(state, "slice_metrics", {}),
                    "link_flags":       getattr(state, "link_flags",    {}),
                    "playing_scenario": _current_id,
                },
            })
        except Exception:
            pass

    state_tasks = [
        asyncio.create_task(_apply_later(p))
        for p in scenario.get("state_changes", [])
    ]

    # Stream the log entries. delay_ms is relative to the previous entry,
    # matching the user-facing script.
    for seq, entry in enumerate(scenario["reasoning_log_entries"]):
        await asyncio.sleep(entry.get("delay_ms", 0) / 1000.0)
        await broadcast({
            "type":      "scenario_log",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "seq":           seq,
                "subtype":       entry.get("type", "analyze"),
                "content":       entry.get("content", ""),
                "is_conclusion": bool(entry.get("is_conclusion", False)),
                "scenario_id":   scenario["id"],
            },
        })

    try:
        # ── Auto-create the scenario's config proposal ────────────────
        # 400ms breath after the final conclusion line so the audience's
        # eye can land on it before the proposal card slides in. This is
        # THE demo money-shot beat — do not remove without a UX review.
        template = SCENARIO_PROPOSAL_TEMPLATES.get(scenario["id"])
        if template:
            await asyncio.sleep(0.4)
            # Late-import to avoid a circular import at module load time.
            from agent import v2_proposals
            payload = dict(template)
            payload.setdefault("triggering_incident_id", scenario["id"])
            created = v2_proposals.create_proposal(payload)
            # Also stash the scenario id so post-approval recovery
            # entries can key off it.
            created["triggering_scenario_id"] = scenario["id"]
            # System-type reasoning log entry announcing the proposal.
            msg = f"Config proposal created · ID {created['id']} · awaiting human approval"
            if scenario["id"] == "transport-congestion-upf-innocent":
                msg = f"Config proposal created · ID {created['id']} · TAC email queued · awaiting human approval"
            await broadcast({
                "type":      "scenario_log",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "seq":         -1,
                    "subtype":     "system",
                    "content":     msg,
                    "is_conclusion": False,
                    "scenario_id": scenario["id"],
                    "proposal_id": created["id"],
                },
            })

        # Let the background state patches finish before signalling
        # completion (some mutations are scheduled late in the window).
        if state_tasks:
            try:
                await asyncio.wait(state_tasks, timeout=scenario["duration_seconds"])
            except Exception:
                pass

        await broadcast({
            "type":      "scenario_complete",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"id": scenario["id"]},
        })
    finally:
        # Clear the 'Playing: Act X' indicator by flipping _current_id
        # and broadcasting one last state_update. Runs even if the task
        # was cancelled mid-stream.
        _current_id = None
        try:
            state = await adapter.get_full_state()
            await broadcast({
                "type": "state_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "nodes":            state.nodes,    "links":         state.links,
                    "lsps":             state.lsps,     "alarms":        state.alarms,
                    "slices":           getattr(state, "slices",        {}),
                    "sessions":         getattr(state, "sessions",      {}),
                    "qer_state":        getattr(state, "qer_state",     {}),
                    "slice_metrics":    getattr(state, "slice_metrics", {}),
                    "link_flags":       getattr(state, "link_flags",    {}),
                    "playing_scenario": None,
                },
            })
        except Exception:
            pass


async def _cancel_current(broadcast, reason: str) -> None:
    global _current_task, _current_id
    if _current_task and not _current_task.done():
        cancelled_id = _current_id
        _current_task.cancel()
        try:
            await _current_task
        except (asyncio.CancelledError, Exception):
            pass
        await broadcast({
            "type": "scenario_stopped",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"id": cancelled_id, "reason": reason},
        })
    _current_task = None
    _current_id   = None


async def inject(scenario_id: str, broadcast, adapter, reset_baseline) -> dict:
    """Start a scenario. If one is already running, cancel it, reset the
    adapter baseline, then begin the new one. ``reset_baseline`` is a
    0-arg callable that restores the adapter to its default state
    (usually ``ContainerlabAdapter()`` re-instantiation, wired in the
    api layer so we don't touch app-global refs from here)."""
    global _current_task, _current_id
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}

    # Interrupt semantics: halt current, reset to baseline, begin new.
    if _current_task and not _current_task.done():
        await _cancel_current(broadcast, reason="interrupted by new injection")
        reset_baseline()

    _current_id   = scenario_id
    _current_task = asyncio.create_task(_play(scenario, broadcast, adapter))
    return {
        "status":           "playing",
        "id":               scenario_id,
        "duration_seconds": scenario["duration_seconds"],
    }


async def stop(broadcast, reset_baseline_if_requested: bool, reset_baseline) -> dict:
    """Halt any in-flight playback. If ``reset_baseline_if_requested``,
    additionally restore the adapter to baseline state."""
    await _cancel_current(broadcast, reason="stopped by operator")
    if reset_baseline_if_requested:
        reset_baseline()
    return {"status": "stopped"}
