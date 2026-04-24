"""
ORCA v2 demo — Email Outbox.

Two templates: an internal NOC notification on Act 1 approval, and a
TAC handoff email with evidence package on Act 2 approval. Both live
as drafts in the outbox until the operator clicks Send.

This is a demo-only store. Nothing is actually sent — SMTP is NOT wired.
Send/discard are pure state transitions that emit reasoning log entries.

Separate from v1 ``agent/notifications.py`` (which backs /api/emails and
is still used by the baseline test suite).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional


FROM_ADDRESS = "orca@noc.operator.example.com"
OPERATOR_PLACEHOLDER = "operator@session"


# ─── Store ────────────────────────────────────────────────────────────

_emails: list = []


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _next_id() -> str:
    return f"em-{int(time.time() * 1000)}"


def get_emails() -> list:
    """Newest-first copy of the email outbox."""
    return [dict(e) for e in _emails]


def clear_all() -> None:
    _emails.clear()


def create(payload: dict) -> dict:
    e = {
        "id":                     _next_id(),
        "type":                   payload.get("type", "internal_ops"),
        "to":                     list(payload.get("to",  [])),
        "cc":                     list(payload.get("cc",  [])),
        "from":                   payload.get("from", FROM_ADDRESS),
        "subject":                payload.get("subject", ""),
        "body":                   payload.get("body", ""),
        "attachments":            [dict(a) for a in payload.get("attachments", [])],
        "status":                 "draft",
        "created_at":             _now_iso(),
        "sent_at":                None,
        "triggering_proposal_id": payload.get("triggering_proposal_id"),
    }
    _emails.insert(0, e)
    return e


def _find(email_id: str) -> Optional[dict]:
    return next((e for e in _emails if e.get("id") == email_id), None)


def mark_sent(email_id: str) -> Optional[dict]:
    e = _find(email_id)
    if not e or e["status"] != "draft":
        return None
    e["status"]  = "sent"
    e["sent_at"] = _now_iso()
    return dict(e)


def discard(email_id: str) -> bool:
    global _emails
    before = len(_emails)
    _emails = [e for e in _emails if e.get("id") != email_id]
    return len(_emails) < before


# ─── Templates ────────────────────────────────────────────────────────

def build_act1_email(proposal: dict) -> dict:
    ts_detected = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    approve_ts  = proposal.get("approved_at") or _now_iso()
    deploy_ts   = proposal.get("deployed_at") or _now_iso()
    pr_url      = proposal.get("pr_url") or "(PR creation pending — check /api/proposals)"
    proposal_id = proposal.get("id", "(unknown)")

    body = (
        f"At {ts_detected}, ORCA detected a dual root cause condition on UPF-01 "
        f"affecting the slice-A enterprise cohort (842 subscribers, $2.4M ARR). "
        f"Session distribution skew had concentrated all active slice-A sessions "
        f"on UPF-01 while QER enforcement had drifted from committed intent "
        f"(32 Mbps enforced vs 50 Mbps GBR). Combined effect was driving p99 N3 "
        f"latency toward the 15ms SLA threshold.\n\n"

        f"ORCA composed an atomic two-change configuration package: (1) QER "
        f"update on UPF-01 restoring slice-A priority class to committed GBR "
        f"of 50 Mbps, and (2) PFCP session modification to rebalance 180 "
        f"high-bandwidth slice-A sessions to UPF-02. All six validation gates "
        f"passed including digital twin simulation.\n\n"

        f"Proposal {proposal_id} was approved by {OPERATOR_PLACEHOLDER} at "
        f"{approve_ts}. Deployment completed in 8 seconds. See GitHub PR: "
        f"{pr_url} for full audit trail and diff.\n\n"

        f"Post-recovery measurements: slice-A p99 N3 latency recovered from "
        f"13.1 ms to 8.9 ms. Enterprise at-risk cohort reduced from 423 to 14 "
        f"subscribers. Revenue-at-risk reduced by $1.16M. Slice-A SLA headroom "
        f"fully restored. No customer-facing impact occurred — intervention "
        f"landed pre-breach.\n\n"

        f"No further action required. Digital twin state updated. Episode "
        f"captured for learned policy review.\n\n"

        f"— ORCA"
    )

    ts_filename = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return {
        "type":                   "internal_ops",
        "to":                     ["noc@operator.example.com"],
        "cc":                     ["slice-ops@operator.example.com",
                                   "customer-experience@operator.example.com"],
        "from":                   FROM_ADDRESS,
        "subject":                "Slice-A QoS recovery on UPF-01 — 842 enterprise subscribers protected",
        "body":                   body,
        "attachments": [
            {"filename": f"slice-a-recovery-evidence-{ts_filename}.json",
             "size_bytes": 14382, "mime_type": "application/json", "content_reference": "internal"},
            {"filename": "upf-01-qer-before-after.yaml",
             "size_bytes": 2108,  "mime_type": "application/yaml", "content_reference": "internal"},
        ],
        "triggering_proposal_id": proposal_id,
    }


def build_act2_email(proposal: dict) -> dict:
    pr_url      = proposal.get("pr_url") or "(PR creation pending — check /api/proposals)"
    proposal_id = proposal.get("id", "(unknown)")
    # OTDR "last clean" — a time roughly 9 hours earlier so the narrative
    # reads "clean this morning, congested now"
    otdr_ts = (datetime.utcnow()
               .replace(hour=max(0, datetime.utcnow().hour - 9),
                        minute=17, second=0, microsecond=0)
               .strftime("%Y-%m-%d %H:%M:%S UTC"))

    body = (
        "ORCA has detected transport-layer congestion on the PE-01 ↔ P-02 link "
        "affecting LSP-1, which carries slice-A enterprise traffic from gNB-1 "
        "to UPF-01. Link utilization reached 93% with microbursts detected in "
        "the last 60 seconds. Combined effect is driving p99 N3 latency on "
        "UPF-01 toward the 15ms slice-A SLA threshold.\n\n"

        "Nokia core elements have been cleared as root cause. UPF-01 CPU, "
        "memory pressure, PFCP association state, and QER enforcement all "
        "healthy. SMF keepalive and AMF session count nominal. Core signaling "
        "plane clean. The fault is upstream of UPF-01, on the transport path.\n\n"

        f"ORCA has deployed a Nokia-domain workaround: PFCP session "
        f"modification to re-anchor 180 slice-A high-bandwidth sessions via "
        f"an alternate path that bypasses the congested PE-01 ↔ P-02 segment. "
        f"Customer-facing impact contained. See GitHub PR: {pr_url} for "
        f"audit trail.\n\n"

        f"Evidence package attached: 60-second telemetry window showing link "
        f"utilization, LSP-1 path state, and slice-A N3 latency correlation. "
        f"OTDR last clean reading: {otdr_ts}. Current link status: congested, "
        f"no physical fault indicators.\n\n"

        "Suggested resolutions for transport team evaluation:\n"
        "  1. Short-term — reroute LSP-1 via P-01 → P-02 alternate path. "
        "IGP metric adjustment on PE-01 to prefer the alternate. Estimated "
        "deployment time: 5 minutes. No capex.\n"
        "  2. Medium-term — rebalance traffic across PE-01 ↔ P-02 and "
        "PE-01 ↔ P-01 by adjusting IGP metrics. Sustained improvement without "
        "capacity addition. Estimated deployment: 30 minutes.\n"
        "  3. Long-term — capacity augment on PE-01 ↔ P-02. 40G → 100G "
        "upgrade. Estimated capex: $180K. Justification: trend analysis shows "
        "this link approaching 80% average utilization over 30 days, "
        "congestion episodes increasing in frequency.\n\n"

        "Please advise on preferred resolution path. ORCA's workaround will "
        "remain in place until the transport congestion is resolved at "
        "source. Reversion plan is pre-staged — see attached rollback spec.\n\n"

        "Contact: orca@noc.operator.example.com for further evidence or "
        "telemetry queries.\n\n"

        "— ORCA (on behalf of Nokia NetOps)"
    )

    ts_filename = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return {
        "type":                   "external_tac",
        "to":                     ["transport-tac@operator.example.com"],
        "cc":                     ["network-ops@operator.example.com"],
        "from":                   FROM_ADDRESS,
        "subject":                "Transport congestion on PE-01 ↔ P-02 — slice-A enterprise impact, Nokia core cleared",
        "body":                   body,
        "attachments": [
            {"filename": f"transport-congestion-evidence-{ts_filename}.json",
             "size_bytes": 24816, "mime_type": "application/json", "content_reference": "internal"},
            {"filename": "lsp-1-path-state-60s-window.json",
             "size_bytes": 9422,  "mime_type": "application/json", "content_reference": "internal"},
            {"filename": "slice-a-n3-latency-correlation.csv",
             "size_bytes": 4218,  "mime_type": "text/csv",         "content_reference": "internal"},
            {"filename": "workaround-rollback-spec.yaml",
             "size_bytes": 1840,  "mime_type": "application/yaml", "content_reference": "internal"},
        ],
        "triggering_proposal_id": proposal_id,
    }


# Scenario id → email template factory
EMAIL_FACTORIES = {
    "slice-a-qos-drift":                  build_act1_email,
    "transport-congestion-upf-innocent":  build_act2_email,
}

# System log entry content used at creation time
DRAFTED_SYSTEM_LOG = {
    "slice-a-qos-drift":                  "NOC notification email drafted · 842 subscriber recovery logged for review",
    "transport-congestion-upf-innocent":  "TAC handoff email drafted · transport team notified with evidence package + 3 suggested resolutions",
}
