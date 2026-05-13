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
import os
from datetime import datetime
from typing import Optional

from agent import customer_intents


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
        # Customers whose risk profile flips to under-fault on inject. Only
        # cust-A (Helix Robotics) rides slice-A; the QER drift hits them
        # specifically. Other LSP-1 tenants are unaffected by this fault.
        "impacted_customers": ["cust-A"],
        # Pre-approval restrictions:
        #  - open_pull_request, write_episode → done by stream_approval
        #    AFTER human approval, not mid-cycle by the agent.
        #  - notify_ops_team, open_tac_case → fired INLINE by the
        #    propose_config_change handler the moment the proposal is
        #    created, so the NOC + TAC emails land simultaneously with
        #    the proposal in the dashboard (no 20-30s sequential-iter gap).
        "restricted_tools": [
            "open_pull_request", "write_episode",
            "notify_ops_team", "open_tac_case",
        ],
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
                "description": "Slice-A p99 trend slope suggests SLA breach within ~10 minutes",
                "source":      "ORCA",
            }},
        ],
        "agent_context": (
            "An info-level alarm on UPF-01 reports that the slice-A p99 N3 latency "
            "trend slope projects an SLA breach within ~10 minutes. SLA is 15 ms; "
            "current p99 is 13.0 ms. No transport alarm is present.\n\n"
            "STEP 0 — FIRST, check the policy library. Call match_policy_intent "
            "with fault_signature={slice_p99_latency_us: 13000, "
            "slice_p99_rising_pct: 5, upf_qer_status: 'gbr_mismatch', "
            "affected_customer_count: 1, customer_arr_at_risk_usd: 2400000}. "
            "If matched=true comes back: skip STEP 1, jump to STEP 2 and call "
            "propose_config_change USING THE MATCHED INTENT'S action.parameters "
            "verbatim. The system has learned this pattern — full diagnosis is "
            "redundant. If matched=false: proceed with STEP 1 as normal.\n\n"
            "Follow this tight 3-step procedure — do not loop:\n\n"
            "STEP 1 — investigate. Call get_qer_state(upf='UPF-01'), "
            "get_slice_metrics(upf='UPF-01'), get_link_utilization(), and "
            "get_link_flags() to confirm the fault is local to UPF (QER drift) "
            "rather than transport.\n\n"
            "STEP 2 — propose. Call propose_config_change with:\n"
            "  - title:  one-line summary (e.g. 'Restore slice-A QER GBR on UPF-01')\n"
            "  - reason: one paragraph naming the alarm, the QER drift values\n"
            "            (enforced vs intent), and the projected impact\n"
            "  - changes: a list with at least one entry naming device='UPF-01'\n"
            "             with type='qer_change' and diff_summary describing the\n"
            "             enforced_mbps restoration\n"
            "  - validation_results: a 6-key object covering syntax, semantic,\n"
            "             mission_1, mission_2, digital_twin, policy\n"
            "  - projected_improvement: one short clause (e.g. 'p99 N3 latency\n"
            "             projected to drop to ~9 ms')\n"
            "The handler automatically queues the NOC + TAC P3 emails IN THE "
            "SAME ITERATION, so the operator sees the proposal AND the two "
            "emails appear together — no need to call notify_ops_team or "
            "open_tac_case yourself.\n\n"
            "STEP 3 — close. Call assess_sla_risk() once. Then stop.\n\n"
            "WITHHELD TOOLS — these have been removed from your schema for "
            "this cycle; do not waste a turn trying to call them:\n"
            "  - notify_ops_team   (fired automatically by propose_config_change)\n"
            "  - open_tac_case     (fired automatically by propose_config_change)\n"
            "  - open_pull_request (happens AFTER human approval in the dashboard)\n"
            "  - write_episode     (happens AFTER human approval in the dashboard)\n"
            "  - reroute_lsp / set_link_metric (not the right fix for QER drift)"
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
        # Resolution path: vendor handles, no Nokia config change, no
        # operator click. Episode is emitted deterministically at end of
        # _play (no stream_approval to pass through). Outcome value must
        # match the Distiller's action.type enum verbatim.
        "episode_at_end_outcome": "vendor_escalation",
        # L5 short-circuit signature. If a ratified policy intent in the
        # PolicyIndex matches this signature, _play skips agent.analyze()
        # entirely, fires the prescribed action deterministically, and
        # emits the episode + a visible "Matched policy" reasoning event.
        # On a cold start (no ratified intent yet), _play falls through
        # to the LLM path. This is the L5 demo punchline: same scenario
        # injects, first run goes through Nemotron (~36s), second run
        # short-circuits (<1s).
        "match_signature": {
            "transport_link_util_pct":  93,
            "upf_qer_status":           "ok",
            "affected_customer_count":  3,
            "core_amf_load_pct":        40,
        },
        # The cross-domain demo moment: three tenants ride LSP-1 — Helix
        # Robotics (5G slice-A), Meridian Capital Markets (MPLS L3VPN),
        # Larkspur Markets (MPLS L3VPN). Same physical congestion event,
        # three customer-specific narratives.
        "impacted_customers": ["cust-A", "cust-B", "cust-C"],
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
            "(currently 14.0 ms; SLA 15 ms). Find the cause and escalate.\n\n"
            "TURN 0 — FIRST, check the policy library. Call match_policy_intent "
            "with fault_signature={transport_link_util_pct: 93, "
            "upf_qer_status: 'ok', affected_customer_count: 3, "
            "core_amf_load_pct: 40}. If matched=true comes back with "
            "action.type='vendor_escalation': skip TURN 1, jump to TURN 2 and "
            "call open_tac_case directly. The system has learned this "
            "pattern — full diagnosis is redundant. If matched=false: proceed "
            "with TURN 1 as normal.\n\n"
            "PARALLELISM IS MANDATORY. Independent read-only tools MUST be "
            "called together in the SAME assistant turn (one message with "
            "multiple tool_calls). Do not call them one-at-a-time across "
            "turns — that wastes seconds per call.\n\n"
            "TURN 1 — emit ALL FOUR diagnostic reads in a single turn, in "
            "parallel:\n"
            "  • get_qer_state(upf='UPF-01')\n"
            "  • get_slice_metrics(upf='UPF-01')\n"
            "  • get_link_utilization()\n"
            "  • get_link_flags()\n"
            "Expected finding: UPF-01 QER healthy, slice metrics confirm the "
            "latency rise without local mis-configuration (Nokia core innocent), "
            "link PE-01-P-02 near capacity with microbursts (transport cause).\n\n"
            "TURN 2 — escalate with exactly ONE email tool:\n"
            "  open_tac_case(\n"
            "    vendor='juniper', node='PE-01',\n"
            "    fault_type='link_congestion', severity='P1',\n"
            "    issue=<one paragraph: alarm details, UPF cleared, transport\n"
            "           link X at Y% with microbursts, Nokia core not at fault>,\n"
            "    resolution_path=<one paragraph addressed to BOTH the Juniper\n"
            "                     transport team AND the internal Nokia NOC.\n"
            "                     Suggest a transport-side fix the Juniper team\n"
            "                     can deploy (e.g. 'Increase IGP metric on\n"
            "                     PE-01-P-02 from 10 to 20 to shift traffic\n"
            "                     onto the alternate path'). Note that Nokia\n"
            "                     has no action — this is informational for\n"
            "                     the NOC and an action request for the\n"
            "                     vendor.>)\n"
            "This single TAC email is the only email this cycle should send. "
            "After the email is queued, STOP — return a final message with no "
            "further tool calls. Do not call write_episode, assess_sla_risk, "
            "or any other tool; the cycle is complete once the TAC case is "
            "opened.\n\n"
            "AUTHORITY — the harness has withheld these tools; do not waste a "
            "turn trying to call them: reroute_lsp, set_link_metric, "
            "propose_config_change, open_pull_request, notify_ops_team, "
            "write_episode, assess_sla_risk. "
            "There is NO Nokia-side config change for this fault."
        ),
        # Authority gate: no LSP/IGP/proposal/PR action (transport not ours).
        # ALSO no notify_ops_team — for Act 2 we want exactly ONE email,
        # the TAC case to Juniper, which covers both the vendor (their
        # action requested) and the internal NOC (Nokia innocent FYI) in
        # the same body. notify_ops_team would be a redundant second copy.
        # write_episode + assess_sla_risk are silent (not displayed in the
        # demo) and were costing one LLM turn (~30s) each cycle for nothing
        # the user can see; restricted out so the cycle stops at the TAC
        # email and finishes in ~2 turns instead of 3.
        "restricted_tools": [
            "reroute_lsp", "set_link_metric", "propose_config_change",
            "open_pull_request", "notify_ops_team",
            "write_episode", "assess_sla_risk",
        ],
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


async def _run_distiller_background(broadcast, episode_yaml: str,
                                     episode_id: str) -> None:
    """Run the Intent Distiller on a freshly-written episode and, on
    success, broadcast `policy_intent_proposed` so the dashboard can
    surface a toast / badge. Pure side-effect helper — no return value,
    no raises (the distiller has its own try/except)."""
    from agent.intent_distiller import distill_episode_safe
    intent = await distill_episode_safe(episode_yaml)
    if not intent:
        return  # distiller logged the no-go reason
    try:
        await broadcast({
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
    except Exception as e:
        print(f"[distiller] broadcast failed (non-fatal): "
              f"{type(e).__name__}: {e}", flush=True)


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

        # 1b. Mark the scenario's impacted customers as under-fault. They
        # will now show their YAML fixture (under-fault) values; everyone
        # else stays at baseline. The Churn donut + Customer Portfolio
        # cards refetch on customer_state_changed and rerender.
        impacted = scenario.get("impacted_customers", [])
        if impacted:
            customer_intents.set_impacted(impacted)
            await broadcast({
                "type":      "customer_state_changed",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {"impacted": list(impacted), "scenario_id": scenario["id"]},
            })

        # 2. Inject the real fault state into the adapter.
        for patch in scenario.get("state_changes", []):
            try:
                adapter.apply_scenario_patch(patch["target"], patch["op"], patch["value"])
            except Exception:
                pass  # don't let one bad patch kill the run
        await _broadcast_state(broadcast, adapter)

        # 2b. L5 SHORT-CIRCUIT — check the ratified PolicyIndex BEFORE
        # spinning up the LLM. If a prior episode of this fault has
        # already been distilled, ratified, and matched against this
        # scenario's match_signature, execute the prescribed action
        # deterministically and skip agent.analyze() entirely. Wall-
        # clock drops from ~36s (LLM diagnosis path) to <1s. This is
        # the demo's L5 win.
        short_circuited = False
        match_sig = scenario.get("match_signature")
        if match_sig and agent is not None:
            try:
                from agent import policy_index as _pi
                hit = _pi.match(match_sig, min_confidence=0.75)
            except Exception as _me:
                hit = None
                print(f"[short-circuit] match failed: "
                      f"{type(_me).__name__}: {_me}", flush=True)
            if hit:
                short_circuited = True
                intent_id = hit.get("intent_id", "")
                action    = hit.get("action") or {}
                act_type  = action.get("type", "")
                conf      = hit.get("confidence", "?")
                # The visible audience marker — drops the L5 win into
                # the reasoning log.
                await broadcast({
                    "type":      "agent_reasoning",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data":      {"text":
                        f"📚 Matched {intent_id} from prior episode — "
                        f"executing prescribed action `{act_type}` "
                        f"directly under guardrail envelope missions-v2. "
                        f"Reasoning skipped (confidence {conf}). "
                        f"L5 closed-loop short-circuit."
                    },
                })
                # Execute the prescribed action. For vendor_escalation,
                # synthesize the same TAC email the LLM path produces.
                # Pattern matches stream_approval's deterministic email
                # composition — no LLM, just send.
                try:
                    if act_type == "vendor_escalation":
                        from agent.notifications import send_email
                        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                        impacted_ids = list(scenario.get("impacted_customers", []))
                        issue = scenario.get("description", "Transport-side fault")
                        resolution = (
                            f"Matched ratified policy intent {intent_id} "
                            f"(confidence {conf}). Action: open TAC case "
                            f"with transport vendor — no Nokia config "
                            f"change. {len(impacted_ids)} customer(s) "
                            f"impacted via shared underlay; informational "
                            f"for NOC, action requested from vendor."
                        )
                        body = (
                            f"1. Issue [P1]: {issue}\n\n"
                            f"2. Resolution Path: {resolution}\n\n"
                            f"Source Policy: {intent_id}\n"
                            f"{ts} | by ORCA (L5 short-circuit)"
                        )
                        ops_email = os.getenv("OPS_EMAIL", "sireenmalik@gmail.com")
                        send_email(
                            to=ops_email,
                            subject=f"[TAC P1] JUNIPER — link_congestion on PE-01",
                            body=body,
                        )
                except Exception as _ae:
                    print(f"[short-circuit] action exec failed: "
                          f"{type(_ae).__name__}: {_ae}", flush=True)

        # 3. Hand control to the agent. The agent's emitted events
        # (agent_thinking, agent_reasoning, tool_call, tool_result,
        # tool_error, security_alert, pr_opened, churn_risk_update,
        # agent_status) flow to the websocket bus via on_agent_event,
        # so the dashboard's reasoning log fills in real time. Skipped
        # when a ratified policy short-circuit already fired the action.
        if agent is not None and not short_circuited:
            # Snapshot the active scenario onto the agent so handlers
            # (propose_config_change) and the post-cycle episode emitter
            # can read the canonical scenario.description + impacted
            # customer list without depending on this module's globals.
            agent._active_scenario = {
                "id":                 scenario["id"],
                "description":        scenario.get("description", ""),
                "impacted_customers": list(scenario.get("impacted_customers", [])),
            }
            try:
                await agent.analyze(
                    context=scenario["agent_context"],
                    restricted_tools=scenario.get("restricted_tools"),
                    effort=scenario.get("effort"),
                )
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

        # 3b. Auto-emit a deterministic episode for resolution paths that
        # don't pass through stream_approval (Act 2: vendor_escalation,
        # no operator click). Act 1 is emitted later in stream_approval
        # after the human approves. Skip if no outcome declared.
        end_outcome = scenario.get("episode_at_end_outcome")
        if end_outcome and agent is not None:
            try:
                impacted_ids = list(scenario.get("impacted_customers", []))
                arr_at_risk_usd = 0
                for cid in impacted_ids:
                    rec = customer_intents.get_by_id(cid) or {}
                    arr_at_risk_usd += int(rec.get("arr_usd", 0) or 0)
                ep_result = await agent._execute_tool("write_episode", {
                    "scenario_id":             scenario["id"],
                    "diagnosis":               scenario.get("description", ""),
                    "outcome":                 end_outcome,
                    "nokia_config_change":     False,
                    "human_involvement":       False,
                    "customers":               impacted_ids,
                    "affected_customer_count": len(impacted_ids),
                    "arr_at_risk":             arr_at_risk_usd,
                    "saved_arr":               0,  # vendor handling — not saved yet
                    "trigger_type":            "transport_congestion",
                    "trigger_description":     scenario.get("description", ""),
                    "reasoning_summary":       (
                        f"ORCA diagnosed transport-side fault on shared LSP. "
                        f"Nokia core innocent ({len(impacted_ids)} customers "
                        f"impacted via shared underlay). Escalated to vendor "
                        f"via single TAC case; no Nokia config change."
                    ),
                    "notifications_sent": ["TAC case opened with transport vendor"],
                    "actions_taken":      ["open_tac_case"],
                })
                # ── Fire the Intent Distiller as a fire-and-forget
                # background task. Non-critical learning loop — failure
                # MUST NOT propagate or delay the demo's scenario_complete
                # signal. distill_episode_safe() never raises by contract.
                try:
                    import json as _json
                    ep_data = _json.loads(ep_result) if isinstance(ep_result, str) else (ep_result or {})
                    episode_yaml = ep_data.get("content", "")
                    if episode_yaml:
                        from agent.intent_distiller import distill_episode_safe
                        asyncio.create_task(
                            _run_distiller_background(
                                broadcast, episode_yaml,
                                ep_data.get("episode_id", ""),
                            )
                        )
                except Exception as _e:
                    print(f"[distiller-trigger] skipped: "
                          f"{type(_e).__name__}: {_e}", flush=True)
            except Exception as e:
                # Non-critical learning loop. Failure must not break the
                # demo flow or the user-facing scenario_complete signal.
                await broadcast({
                    "type":      "scenario_log",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "subtype":     "info",
                        "content":     f"episode emit skipped: {type(e).__name__}: {str(e)[:160]}",
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

    Every inject starts from a CLEAN baseline — any residual state from
    the previous scenario (alarms, link util, QER drift, customer impact,
    cycle artifacts, dedup signature) is wiped before the new fault is
    applied. We don't simulate two compound faults at once today.
    ``reset_baseline`` is a 0-arg callable that re-instantiates the
    adapter; ``agent`` is the live ORCAAgent.
    """
    global _current_task, _current_id
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}

    # 1. Cancel any in-flight cycle first.
    if _current_task and not _current_task.done():
        await _cancel_current(broadcast, reason="interrupted by new injection")

    # 2. ALWAYS reset baseline before applying new fault state. This is
    #    independent of whether a task was running — if Act 2 completed
    #    earlier and left transport congestion in the adapter, injecting
    #    Act 1 next must NOT see that residual state.
    reset_baseline()
    customer_intents.clear_impacted()
    if hasattr(agent, "reset_fault_signature"):
        agent.reset_fault_signature()
    # Tell the dashboard the portfolio just went green.
    await broadcast({
        "type":      "customer_state_changed",
        "timestamp": datetime.utcnow().isoformat(),
        "data":      {"impacted": [], "reason": "scenario_inject_reset"},
    })

    # 3. reset_baseline() rebinds the api module's global adapter AND
    #    agent.adapter to a fresh instance. The ``adapter`` argument we
    #    captured at call time is now stale — pull the live adapter from
    #    agent.adapter for the play.
    live_adapter = getattr(agent, "adapter", adapter) if agent else adapter

    _current_id   = scenario_id
    _current_task = asyncio.create_task(_play(scenario, broadcast, live_adapter, agent))
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
