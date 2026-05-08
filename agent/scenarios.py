"""
ORCA — fault-injection scenarios (NIMO branch).

The two scenarios mirror what the v2 demo's Act 1 / Act 2 *staged*, but
on the NIMO branch they are no longer scripted playback. Each scenario:

  1. Broadcasts ``scenario_started`` so the UI shows the running label.
  2. Applies a set of state mutations to the adapter via
     ``adapter.apply_scenario_patch(...)`` — these create the **real**
     fault condition (QER drift, link congestion, microbursts, alarm).
  3. Calls ``agent.analyze(context=...)`` once with a short
     scenario-specific seed message. The agent uses its real tools
     (get_topology, get_link_utilization, get_qer_state,
     get_slice_metrics, get_link_flags, ... reroute_lsp,
     propose_config_change, open_pull_request, write_episode, ...) to
     diagnose, decide, and act. Reasoning, tool calls, proposals,
     emails, PRs, and episodes are all driven by the LLM substrate
     (NIM Nemotron or Anthropic Claude — selected via LLM_PROVIDER).
  4. Broadcasts ``scenario_complete`` when ``analyze()`` returns.

No scripted reasoning_log_entries, no SCENARIO_PROPOSAL_TEMPLATES, no
SCENARIO_RECOVERY_ENTRIES — those lived on demo/5g-ran for a 7-minute
deterministic stage demo and are removed here so the agent path is
faithful to a real Nokia-lab deployment.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional


# ─── Scenario definitions ────────────────────────────────────────────────────

SCENARIOS = {
    # ═══════════════ Slice-A QoS degradation on UPF-01 ═══════════════════════
    # Real fault: QER on UPF-01 slice-A enforces 32 Mbps against a 50 Mbps GBR
    # intent. Slice-A p99 N3 latency climbs from 11.2 → 13.0 ms. An info-level
    # alarm fires noting the trend. The agent must read QER state + slice
    # metrics, conclude this is local to the UPF (not transport), and
    # propose restoring the QER.
    "slice-a-qos-drift": {
        "id":                "slice-a-qos-drift",
        "name":              "Slice-A QoS degradation on UPF-01",
        "short_label":       "Slice-A QoS drift",
        "description":       "QER drift on UPF-01 slice-A priority class: enforced 32 Mbps vs committed 50 Mbps GBR.",
        "duration_seconds":  45,
        "state_changes": [
            # QER drift: enforced rate sits 36% below committed GBR.
            {"target": "qer_state.UPF-01.slice-A", "op": "set",
             "value": {"intent_gbr_mbps": 50, "enforced_mbps": 32, "status": "drifted"}},
            # p99 N3 latency at 13.0 ms — climbing toward 15 ms SLA.
            {"target": "metrics.UPF-01.slice_A.p99_ms", "op": "set", "value": 13.0},
            # Pre-threshold info alarm — agent's only push signal.
            {"target": "alarms", "op": "append", "value": {
                "id":          "info-slice-a-p99-trend",
                "severity":    "info",
                "node":        "UPF-01",
                "description": "Slice-A p99 trend slope suggests SLA breach within 4 minutes",
                "source":      "ORCA",
            }},
        ],
        "agent_context": (
            "An info-level alarm on UPF-01 reports that the slice-A p99 N3 latency "
            "trend slope projects an SLA breach within ~4 minutes. SLA is 15 ms; "
            "current p99 is 13.0 ms. No transport alarm is present. Investigate the "
            "root cause across UPF-local state (QER enforcement, slice metrics) and "
            "transport telemetry (link utilization, link flags), decide whether the "
            "fault is local to UPF or upstream, and act per the standard ORCA cycle "
            "including notify_ops_team, propose_config_change, open_pull_request, "
            "write_episode, and assess_sla_risk."
        ),
    },

    # ═════════════ Transport congestion, Nokia core innocent ═════════════════
    # Real fault: link PE-01 ↔ P-02 sits at 93% with microbursts. UPF-01
    # local state is healthy. Slice-A p99 climbs to 14.0 ms because LSP-1
    # carries it through the congested link. Agent must walk the local-vs-
    # upstream chain, conclude transport is the cause, and emit a handoff
    # (Nokia has no action authority over transport).
    "transport-congestion-upf-innocent": {
        "id":                "transport-congestion-upf-innocent",
        "name":              "Transport congestion on LSP-1, UPF-01 innocent",
        "short_label":       "Transport congestion (UPF innocent)",
        "description":       "PE-01↔P-02 at 93% with microbursts. UPF/SMF/AMF healthy — fault is upstream of Nokia scope.",
        "duration_seconds":  60,
        "state_changes": [
            {"target": "link_util.PE-01-P-02",              "op": "set", "value": 93.0},
            {"target": "link_flags.PE-01-P-02.microbursts", "op": "set", "value": True},
            {"target": "metrics.LSP-1.util_pct",            "op": "set", "value": 93.0},
            {"target": "metrics.UPF-01.slice_A.p99_ms",     "op": "set", "value": 14.0},
            {"target": "alarms", "op": "append", "value": {
                "id":          "warn-slice-a-p99-rising",
                "severity":    "warning",
                "node":        "UPF-01",
                "description": "Slice-A p99 latency rising on UPF-01",
                "source":      "monitoring",
            }},
        ],
        "agent_context": (
            "A warning alarm reports slice-A p99 N3 latency climbing on UPF-01 "
            "(currently 14.0 ms; SLA 15 ms). Determine whether the cause is "
            "local to the Nokia core (UPF QER, SMF, AMF, session state) or "
            "upstream in the transport (LSP path utilization, microbursts, link "
            "flags). Use get_qer_state and get_slice_metrics to clear local "
            "Nokia-side hypotheses, then expand to get_link_utilization and "
            "get_link_flags on the LSP-1 path. If the fault is transport-side, "
            "Nokia has read-only authority — do not attempt MPLS reconfiguration; "
            "instead escalate via open_tac_case (vendor='nokia' is wrong here — "
            "use 'nokia' only for Nokia-domain faults) and notify_ops_team, then "
            "still write_episode and assess_sla_risk to close the cycle."
        ),
    },
}


# ─── Playback engine ─────────────────────────────────────────────────────────
#
# One module-level task holds the current run. A new inject cancels the old.

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
    if _current_task and not _current_task.done():
        return _current_id
    return None


async def _broadcast_state(broadcast, adapter) -> None:
    try:
        state = await adapter.get_full_state()
    except Exception:
        return
    await broadcast({
        "type":      "state_update",
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


async def _play(scenario: dict, broadcast, adapter, agent) -> None:
    """Apply the fault, hand control to the agent, signal complete."""
    global _current_id
    try:
        # 1. UI marker
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

        # 2. Inject the real fault state into the adapter.
        for patch in scenario.get("state_changes", []):
            try:
                adapter.apply_scenario_patch(patch["target"], patch["op"], patch["value"])
            except Exception:
                pass  # don't let one bad patch kill the run
        await _broadcast_state(broadcast, adapter)

        # 3. Hand control to the agent. The agent's emitted events
        # (agent_thinking, agent_reasoning, tool_call, tool_result,
        # tool_error, security_alert, pr_opened, churn_risk_update,
        # agent_status) flow to the websocket bus via on_agent_event,
        # so the dashboard's reasoning log fills in real time.
        if agent is not None:
            try:
                await agent.analyze(context=scenario["agent_context"])
            except Exception as e:
                await broadcast({
                    "type":      "scenario_log",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "subtype":     "alert",
                        "content":     f"agent.analyze() raised: {type(e).__name__}: {str(e)[:200]}",
                        "scenario_id": scenario["id"],
                    },
                })

        # 4. Done.
        await broadcast({
            "type":      "scenario_complete",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"id": scenario["id"]},
        })
    finally:
        _current_id = None
        await _broadcast_state(broadcast, adapter)


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
            "type":      "scenario_stopped",
            "timestamp": datetime.utcnow().isoformat(),
            "data":      {"id": cancelled_id, "reason": reason},
        })
    _current_task = None
    _current_id   = None


async def inject(scenario_id: str, broadcast, adapter, reset_baseline, agent) -> dict:
    """Apply scenario fault state and trigger one agent.analyze() cycle.

    If a scenario is already running, cancel it, reset the adapter, then
    begin the new one. ``reset_baseline`` is a 0-arg callable that
    re-instantiates the adapter; ``agent`` is the live ORCAAgent.
    """
    global _current_task, _current_id
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}

    if _current_task and not _current_task.done():
        await _cancel_current(broadcast, reason="interrupted by new injection")
        reset_baseline()

    _current_id   = scenario_id
    _current_task = asyncio.create_task(_play(scenario, broadcast, adapter, agent))
    return {
        "status":           "playing",
        "id":               scenario_id,
        "duration_seconds": scenario["duration_seconds"],
    }


async def stop(broadcast, reset_baseline_if_requested: bool, reset_baseline) -> dict:
    await _cancel_current(broadcast, reason="stopped by operator")
    if reset_baseline_if_requested:
        reset_baseline()
    return {"status": "stopped"}
