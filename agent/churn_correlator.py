"""
agent/churn_correlator.py — Demo #3 customer-drill-in correlator

Given a customer id, gather:
  1. The customer fixture (industry, headline use case, AE, ARR, NPS,
     contract pressure, competitor activity, etc.)
  2. The current network telemetry on the customer's service underlay
     (link util, microbursts, slice metrics, QER state, alarms).

Hand both to Nemotron with ``low_effort=True`` and ask for a structured
causal explanation: churn %, top risk drivers, recommended action, and
an executive summary addressed to the AE by first name.

This is the per-customer drill-in that the dashboard renders when the
operator clicks a row in the churn tab. It is the demo's proof of ORCA's
single-agent cross-domain reasoning — the same network event becomes a
*different* story for each customer based on industry context, service
type, and contract pressure.
"""
from __future__ import annotations

import json

from agent import customer_intents


SYSTEM_PROMPT = """You are an ORCA customer-risk analyst.

Given a customer profile and the current network telemetry for the
service they ride on, produce a JSON object explaining their churn
risk in customer-specific business language. Address the executive
summary to the account exec by first name.

Respond with ONLY a JSON object — no preamble, no markdown fence.

Required fields:
{
  "churn_pct":   <integer 0-100 — your estimate of churn probability
                  over the next 60 days given current state>,
  "risk_drivers": [
    <3-5 short strings; each names one specific cause grounded in
     either the customer profile or the telemetry. Be concrete:
     name the slice, the LSP, the microburst, the renewal date,
     the lingering ticket, the competitor — whichever applies.>
  ],
  "recommended_action": <one short string — what we should do for them>,
  "executive_summary": <2-3 sentences addressed to the AE by first
                        name, naming the customer, naming the cause in
                        domain-appropriate language (5G slice, MPLS
                        L3VPN, optical wavelength), tying it to a
                        business impact (renewal pressure, $ARR at
                        renewal, NPS drop, audit/regulatory tail,
                        competitor activity).>
}

Tone: precise, account-management voice. Not generic. The summary
should sound like it was written by an analyst who actually understood
THIS customer's business — referencing their specific use case, their
specific service type, their specific risk vector. If the network is
clean for this customer, say so and explain the *non-network* risk
drivers (renewal cycle, NPS recovery, competitor, billing dispute)."""


async def _gather_telemetry(adapter, customer: dict) -> dict:
    """Pull just the live telemetry slices relevant to this customer's
    service. Anything outside the customer's domain is omitted to keep
    the prompt tight and the reasoning focused."""
    service = customer.get("service") or {}
    underlay = service.get("underlay", "")
    svc_type = service.get("type", "")
    svc_id   = service.get("id", "")

    state = await adapter.get_full_state()
    alarms = state.alarms or []
    alarm_descs = []
    for a in alarms[:4]:
        if isinstance(a, dict):
            alarm_descs.append(a.get("description", ""))
        else:
            alarm_descs.append(getattr(a, "description", ""))

    out: dict = {
        "service":         {"type": svc_type, "id": svc_id, "underlay": underlay},
        "current_alarms":  alarm_descs,
        "link_utilization": {
            lid: {
                "util_pct": round(l.get("utilization_pct", 0), 1),
                "state":    l.get("state", "up"),
            }
            for lid, l in (state.links or {}).items()
        },
    }

    # 5G-specific surfaces
    if svc_type.startswith("5g"):
        if hasattr(adapter, "get_qer_state"):
            qer = adapter.get_qer_state() or {}
            # Filter to just this slice
            out["qer_state"] = {
                upf: per_slice[svc_id]
                for upf, per_slice in qer.items()
                if isinstance(per_slice, dict) and svc_id in per_slice
            }
        if hasattr(adapter, "get_slice_metrics"):
            metrics = adapter.get_slice_metrics() or {}
            out["slice_metrics"] = metrics

    # MPLS-specific surfaces
    if svc_type == "mpls-l3vpn":
        if hasattr(adapter, "get_link_flags"):
            flags = adapter.get_link_flags() or {}
            # Trim to just the underlay link's flags if it matches a link id;
            # otherwise include the whole map for the model to scan.
            out["link_flags"] = flags

    # Optical: no telemetry surface in the lab adapter today — be honest
    if svc_type == "optical-wave":
        out["optical_note"] = (
            "Optical telemetry surface (BER, OSNR, attenuation) is not yet "
            "wired in this lab adapter. Assume clean unless an alarm says "
            "otherwise."
        )

    return out


def _strip_fences(s: str) -> str:
    """Some models wrap JSON in ```json ... ``` despite instructions. Strip."""
    s = s.strip()
    if s.startswith("```"):
        # split off the leading fence
        first_nl = s.find("\n")
        if first_nl > 0:
            s = s[first_nl + 1:]
        # strip trailing fence if present
        if s.endswith("```"):
            s = s[: -3].rstrip()
    return s.strip()


async def correlate(customer_id: str, agent) -> dict:
    """Build the prompt, call Nemotron with low_effort, return the structured
    result. ``agent`` is the live ORCAAgent — we use its client + adapter."""
    customer = customer_intents.get_by_id(customer_id)
    if not customer:
        return {"error": f"customer not found: {customer_id}"}

    if agent.provider != "nim":
        return {
            "error":     "correlator is currently NIM-only",
            "provider":  agent.provider,
            "customer_id": customer_id,
        }

    telemetry = await _gather_telemetry(agent.adapter, customer)

    user_msg = json.dumps(
        {"customer_profile": customer, "current_telemetry": telemetry},
        indent=2,
        default=str,
    )

    try:
        response = await agent.client.chat.completions.create(
            model=agent.model,
            max_tokens=1500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            extra_body={"chat_template_kwargs": {"enable_thinking": True, "low_effort": True}},
        )
    except Exception as e:
        return {
            "error":       f"NIM call failed: {type(e).__name__}: {str(e)[:200]}",
            "customer_id": customer_id,
        }

    content = (response.choices[0].message.content or "")
    content = _strip_fences(content)

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "executive_summary":   content[:800],
            "churn_pct":           None,
            "risk_drivers":        [],
            "recommended_action":  None,
            "_parse_error":        "model did not return valid JSON",
        }

    # Stamp the customer context so the dashboard doesn't have to do a
    # second fetch to render the side panel.
    result["customer_id"]   = customer_id
    result["customer_name"] = customer.get("name")
    result["account_exec"]  = customer.get("account_exec")
    result["arr_usd"]       = customer.get("arr_usd")
    result["service_type"]  = (customer.get("service") or {}).get("type")
    result["service_id"]    = (customer.get("service") or {}).get("id")
    return result
