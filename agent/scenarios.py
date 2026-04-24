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
        "description":       "QER drift on UPF-01 slice-A priority class: enforced 32 Mbps vs committed 50 Mbps GBR. Pre-threshold detect, single atomic fix.",
        "duration_seconds":  45,
        # State evolves from t=0 over ~45s. Each entry is an absolute
        # offset from scenario start (milliseconds). The playback engine
        # schedules them as independent tasks so a high-density state
        # sweep doesn't block the log stream.
        "state_changes": [
            # QER drift flag flips at t=3s. Enforced rate has accumulated
            # drift from successive config pushes and now sits 36% below
            # committed GBR. No alarm — SLA still green — but slice-A
            # traffic is being throttled below contract.
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
            {"delay_ms": 200,  "type": "analyze",  "content": "Checking UPF-01 QER state for slice-A priority class..."},
            {"delay_ms": 400,  "type": "analyze",  "content": "QER table: slice-A priority class committed GBR = 50 Mbps. Currently enforced = 32 Mbps. Drift: -36% from intent."},
            {"delay_ms": 200,  "type": "correlate","content": "Correlating: slice-A packets on UPF-01 throttled below committed rate. Queue buildup at the enforcement point explains p99 climb. Root cause localized."},
            {"delay_ms": 2500, "type": "conclude", "is_conclusion": True,
             "content": "Diagnosis complete. Single root cause: QER drift on UPF-01 slice-A priority class. Current enforcement does not match committed SLA."},
            {"delay_ms": 400,  "type": "decide",   "content": "Composing config change. QER update on UPF-01 restoring slice-A GBR to 50 Mbps (committed intent). Enforcement mode: strict. One atomic PFCP Session Modification."},
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
            {"delay_ms": 400,  "type": "decide",   "content": "ORCA has read-only access to transport. No Nokia-side action is appropriate — the fault is not in Nokia scope."},
            {"delay_ms": 300,  "type": "decide",   "content": "ORCA has no action authority over transport. Fault is upstream of Nokia scope. Composing handoff package for transport team."},
            {"delay_ms": 300,  "type": "decide",   "content": "Drafting TAC email to operator transport team with evidence package and three suggested transport-side resolutions."},
            {"delay_ms": 500,  "type": "conclude", "is_conclusion": True,
             "content": "Handoff package complete. TAC email auto-sent to transport team with evidence and three suggested resolutions. Nokia scope closed."},
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
        "summary": "Restore QER GBR to 50 Mbps on UPF-01",
        "reason": (
            "QER drift detected on UPF-01 affecting slice-A enterprise cohort (842 accounts, "
            "$2.4M ARR). Current enforcement for slice-A priority class is 32 Mbps against a "
            "committed GBR of 50 Mbps — a 36% shortfall accumulated from successive config "
            "changes. Traffic is being throttled below contract, driving p99 N3 latency toward "
            "the 15ms SLA threshold. No alarm has fired yet; detection is pre-breach via trend "
            "slope analysis. Fix is a single atomic QER restoration."
        ),
        "projected_impact": (
            "p99 N3 latency returns to 8.9ms · 842 enterprise accounts protected · "
            "$2.4M ARR cohort preserved"
        ),
        "devices": [
            {"id": "UPF-01", "note": "qer_change", "label": "UPF-01 · qer_change"},
        ],
        "device_diffs": {
            "UPF-01": [
                {"type": "context", "line": "upf: UPF-01"},
                {"type": "context", "line": "qer_profiles:"},
                {"type": "context", "line": "  slice-A-priority:"},
                {"type": "context", "line": "    intent_gbr_mbps: 50           # committed SLA"},
                {"type": "remove",  "line": "    enforced_mbps: 32             # DRIFT -36% from intent"},
                {"type": "add",     "line": "    enforced_mbps: 50             # restored to intent"},
                {"type": "add",     "line": "    enforcement_mode: strict      # hard guarantee"},
                {"type": "context", "line": "    mbr_downlink: 100"},
                {"type": "context", "line": "    mbr_uplink: 100"},
                {"type": "context", "line": "    priority_level: 3"},
            ],
        },
        "device_configs": {
            "UPF-01": (
                "upf: UPF-01\n"
                "qer_profiles:\n"
                "  slice-A-priority:\n"
                "    intent_gbr_mbps: 50           # committed SLA\n"
                "    enforced_mbps: 50             # restored to intent\n"
                "    enforcement_mode: strict      # hard guarantee\n"
                "    mbr_downlink: 100\n"
                "    mbr_uplink: 100\n"
                "    priority_level: 3\n"
            ),
        },
        # Flat diff retained for the compact card preview (it uses .slice(0,8)).
        "diff": [
            {"type": "context", "line": "upf: UPF-01"},
            {"type": "context", "line": "qer_profiles:"},
            {"type": "context", "line": "  slice-A-priority:"},
            {"type": "context", "line": "    intent_gbr_mbps: 50           # committed SLA"},
            {"type": "remove",  "line": "    enforced_mbps: 32             # DRIFT -36% from intent"},
            {"type": "add",     "line": "    enforced_mbps: 50             # restored to intent"},
            {"type": "add",     "line": "    enforcement_mode: strict      # hard guarantee"},
        ],
        "validation_gates": [
            {"name": "Syntax",                "status": "pass",
             "detail": "Valid YAML · QER IE structure per TS 29.244 · fields well-formed"},
            {"name": "Semantic",              "status": "pass",
             "detail": "UPF-01 reachable · slice-A QoS profile exists · QCI-to-QoS mapping valid"},
            {"name": "Mission · utilization", "status": "pass",
             "detail": "No transport impact · all N3 links remain < 90%"},
            {"name": "Mission · slice SLA",   "status": "pass",
             "detail": "slice-A p99 projected to return to 8.9ms within 15ms SLA · slice-B unaffected"},
            {"name": "Digital twin",          "status": "pass",
             "detail": "60s simulated traffic with corrected QER · SLA maintained throughout · no new anomalies"},
            {"name": "Policy",                "status": "pass",
             "detail": "QER value 50 Mbps within operator-approved range (1-100 Mbps)"},
        ],
        "triggering_incident_id": "slice-a-qos-drift",
    },

    "transport-congestion-upf-innocent": {
        "title": "Slice-A session migration off congested LSP-1",
        "summary": "Re-anchor 180 slice-A sessions via alternate path bypassing PE-01 ↔ P-02",
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
        "devices": [
            {"id": "UPF-01", "note": "session re-anchoring only",
             "label": "UPF-01 · session_re_anchor"},
        ],
        "device_diffs": {
            "UPF-01": [
                {"type": "context", "line": "upf: UPF-01"},
                {"type": "context", "line": "pfcp_sessions:"},
                {"type": "context", "line": "  slice-A:"},
                {"type": "remove",  "line": "    preferred_path: LSP-1"},
                {"type": "add",     "line": "    preferred_path: alternate_bypass_PE-01_to_P-02"},
                {"type": "add",     "line": "    rollback_plan: restore_LSP-1_on_transport_clear"},
            ],
        },
        "device_configs": {
            "UPF-01": (
                "upf: UPF-01\n"
                "pfcp_sessions:\n"
                "  slice-A:\n"
                "    preferred_path: alternate_bypass_PE-01_to_P-02\n"
                "    rollback_plan: restore_LSP-1_on_transport_clear\n"
            ),
        },
        "diff": [
            {"type": "context", "line": "upf: UPF-01"},
            {"type": "context", "line": "pfcp_sessions:"},
            {"type": "context", "line": "  slice-A:"},
            {"type": "remove",  "line": "    preferred_path: LSP-1"},
            {"type": "add",     "line": "    preferred_path: alternate_bypass_PE-01_to_P-02"},
            {"type": "add",     "line": "    rollback_plan: restore_LSP-1_on_transport_clear"},
        ],
        "validation_gates": [
            {"name": "Syntax",                "status": "pass",
             "detail": "Valid YAML · PFCP modification IE structure per TS 29.244"},
            {"name": "Semantic",              "status": "pass",
             "detail": "UPF-01 reachable · alternate path configuration valid · session IDs valid"},
            {"name": "Mission · utilization", "status": "pass",
             "detail": "Alternate path utilization stays < 80% · LSP-1 bypass effective"},
            {"name": "Mission · slice SLA",   "status": "pass",
             "detail": "slice-A p99 projected recovery within 15 ms SLA"},
            {"name": "Digital twin",          "status": "pass",
             "detail": "60s simulated with session re-anchoring · transport congestion bypassed successfully"},
            {"name": "Policy",                "status": "pass",
             "detail": "Session migration batch size and timing within human-approved limits"},
        ],
        "triggering_incident_id": "transport-congestion-upf-innocent",
    },
}


# Scenario-specific post-deploy recovery log entries, streamed sequentially
# (200-400ms between) after /api/proposals/{id}/approve completes the
# deploy simulation. Rendered with type="recovered" for green styling.
SCENARIO_RECOVERY_ENTRIES = {
    "slice-a-qos-drift": [
        {"delay_ms": 200, "content": "QER update on UPF-01 committed · slice-A priority class now enforcing GBR 50 Mbps · strict mode active"},
        {"delay_ms": 400, "content": "Slice-A p99 N3 latency recovered: 13.1ms → 8.9ms · SLA headroom restored"},
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
        # ── Act 2: email-only handoff (no proposal, no approval, no
        # deploy). After the final conclude line fires, immediately
        # auto-send the TAC email and emit one system log entry. Nokia
        # scope closes here. Everything below this branch is the
        # proposal-flow path used by Act 1.
        if scenario["id"] == "transport-congestion-upf-innocent":
            await asyncio.sleep(0.4)
            from agent import v2_emails
            handoff = v2_emails.create(
                v2_emails.build_act2_tac_handoff(scenario_id=scenario["id"])
            )
            await broadcast({
                "type":      "email_created",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "id":      handoff["id"],
                    "type":    handoff["type"],
                    "subject": handoff["subject"],
                    "tag":     handoff.get("tag"),
                    "status":  handoff.get("status"),
                },
            })
            await broadcast({
                "type":      "scenario_log",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "seq":           -2,
                    "subtype":       "system",
                    "content":       v2_emails.ACT2_HANDOFF_LOG,
                    "is_conclusion": False,
                    "scenario_id":   scenario["id"],
                    "email_id":      handoff["id"],
                },
            })
            # fall through to the state_patches + scenario_complete block
            # below via the `pass` sentinel instead of returning — the
            # scenario still needs to broadcast its completion.
            template = None
        else:
            template = SCENARIO_PROPOSAL_TEMPLATES.get(scenario["id"])

        # ── Auto-create the scenario's config proposal (Act 1 path) ──
        # 400ms breath after the final conclusion line so the audience's
        # eye can land on it before the proposal card slides in. This is
        # THE demo money-shot beat — do not remove without a UX review.
        if template:
            await asyncio.sleep(0.4)
            # Late-import to avoid a circular import at module load time.
            from agent import v2_proposals, v2_emails
            payload = dict(template)
            payload.setdefault("triggering_incident_id", scenario["id"])
            created = v2_proposals.create_proposal(payload)
            created["triggering_scenario_id"] = scenario["id"]

            # ── Early notification email (pre-approval, auto-SENT) ─────
            # Fires BEFORE we announce the proposal in the reasoning log
            # so the visual flow is:
            #   CONCLUDE ("Proposal ready for human approval.")
            #   SYSTEM   ("Early notification sent to NOC...")
            #   SYSTEM   ("Config proposal created · ID v2-cfg-... awaiting approval")
            # which matches Prompt-9's "between the conclude and card
            # materialization" spec.
            early_factory = v2_emails.EARLY_EMAIL_FACTORIES.get(scenario["id"])
            if early_factory:
                early_payload = early_factory(created)
                early = v2_emails.create(early_payload)
                await broadcast({
                    "type":      "email_created",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "id":                     early["id"],
                        "type":                   early["type"],
                        "subject":                early["subject"],
                        "tag":                    early.get("tag"),
                        "status":                 early.get("status"),
                        "triggering_proposal_id": created["id"],
                    },
                })
                early_log = v2_emails.EARLY_SYSTEM_LOG.get(scenario["id"])
                if early_log:
                    await broadcast({
                        "type":      "scenario_log",
                        "timestamp": datetime.utcnow().isoformat(),
                        "data": {
                            "seq":           -2,
                            "subtype":       "system",
                            "content":       early_log,
                            "is_conclusion": False,
                            "scenario_id":   scenario["id"],
                            "proposal_id":   created["id"],
                            "email_id":      early["id"],
                        },
                    })

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
