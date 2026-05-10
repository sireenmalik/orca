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
    """Create an email. Accepts explicit ``status`` in the payload so
    auto-sent early notifications can skip the draft state."""
    status = payload.get("status") or "draft"
    now = _now_iso()
    e = {
        "id":                     _next_id(),
        "type":                   payload.get("type", "internal_ops"),
        "tag":                    payload.get("tag"),  # e.g. early_notification / post_deploy_resolution
        "to":                     list(payload.get("to",  [])),
        "cc":                     list(payload.get("cc",  [])),
        "from":                   payload.get("from", FROM_ADDRESS),
        "subject":                payload.get("subject", ""),
        "body":                   payload.get("body", ""),
        "attachments":            [dict(a) for a in payload.get("attachments", [])],
        "status":                 status,
        "created_at":             now,
        "sent_at":                now if status == "sent" else None,
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

# ── Early-notification (pre-approval, auto-sent) ─────────────────────

def build_act1_early_email(proposal: dict) -> dict:
    proposal_id = proposal.get("id", "(unknown)")
    body = (
        "At " + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC") + ", ORCA detected "
        "QER drift on UPF-01 affecting the slice-A enterprise cohort (842 accounts, "
        "$2.4M ARR). Slice-A priority class is currently enforcing 32 Mbps against "
        "a committed GBR of 50 Mbps — a 36% shortfall accumulated from successive "
        "config changes. p99 N3 latency is trending toward the 15 ms SLA threshold.\n\n"

        "ORCA is proposing a single-change restoration: QER update on UPF-01 "
        "bringing slice-A priority class back to committed 50 Mbps GBR with strict "
        "enforcement mode. All six validation gates (syntax, semantic, mission "
        "utilization, mission slice SLA, digital twin, policy) have passed.\n\n"

        f"Proposal {proposal_id} is currently PENDING human approval. No action "
        "has been taken on the network yet. This notification is for awareness; "
        "the resolution email will follow upon deployment.\n\n"

        "— ORCA"
    )
    return {
        "type":                   "internal_ops",
        "tag":                    "early_notification",
        "to":                     ["noc@operator.example.com"],
        "cc":                     ["slice-ops@operator.example.com"],
        "from":                   FROM_ADDRESS,
        "subject":                "ORCA diagnosis — Slice-A QoS degradation on UPF-01, proposal pending approval",
        "body":                   body,
        "attachments":            [],
        "status":                 "sent",
        "triggering_proposal_id": proposal_id,
    }


# Scenario id → early-email factory.
# Act 2 is NOT in this map (it uses email-only handoff — see
# ``build_act2_tac_handoff`` below — so there's no pre-approval
# heads-up plus post-deploy resolution pair).
EARLY_EMAIL_FACTORIES = {
    "slice-a-qos-drift": build_act1_early_email,
}
EARLY_SYSTEM_LOG = {
    "slice-a-qos-drift": "Early notification sent to NOC · subject: ORCA diagnosis — Slice-A QoS degradation on UPF-01, proposal pending approval",
}


# ── Act 2 email-only handoff (single auto-sent email, no proposal) ──
#
# Replaces the Prompt-9 early + post-deploy pair for Act 2. Narrative is:
# ORCA diagnoses, hands off to transport team, Nokia scope closed. No
# Nokia-side action is taken, so there's no workaround paragraph and no
# 'workaround rollback spec' attachment — the rollback spec is renamed
# to transport-handoff-evidence-summary.yaml.

def build_act2_tac_handoff(scenario_id: str = "transport-congestion-upf-innocent",
                           proposal_id: str = None) -> dict:
    otdr_ts = (datetime.utcnow()
               .replace(hour=max(0, datetime.utcnow().hour - 9),
                        minute=17, second=0, microsecond=0)
               .strftime("%Y-%m-%d %H:%M:%S UTC"))

    body = (
        "ORCA has detected transport-layer congestion on the PE-01 ↔ P-02 link "
        "affecting LSP-1, which carries slice-A enterprise traffic from gNB-1 "
        "to UPF-01. Link utilization reached 93% with microbursts detected in "
        "the last 60 seconds. Combined effect is driving p99 N3 latency on "
        "UPF-01 toward the 15 ms slice-A SLA threshold.\n\n"

        "Nokia core elements have been cleared as root cause. UPF-01 CPU, "
        "memory pressure, PFCP association state, and QER enforcement all "
        "healthy. SMF keepalive and AMF session count nominal. Core signaling "
        "plane clean. The fault is upstream of UPF-01, on the transport path.\n\n"

        "ORCA has taken no action on Nokia equipment. Transport congestion is "
        "outside Nokia's scope. This email is the handoff package — evidence, "
        "diagnosis, and suggested resolutions for your team's evaluation.\n\n"

        f"Evidence package attached: 60-second telemetry window showing link "
        f"utilization, LSP-1 path state, and slice-A N3 latency correlation. "
        f"OTDR last clean reading: {otdr_ts}. Current link status: congested, "
        f"no physical fault indicators.\n\n"

        "Suggested resolutions for transport team evaluation:\n"
        "  1. Short-term — reroute LSP-1 via P-01 → P-02 alternate path. "
        "IGP metric adjustment on PE-01 to prefer the alternate. Estimated "
        "deployment time: 5 minutes. No capex.\n"
        "  2. Medium-term — redistribute traffic across PE-01 ↔ P-02 and "
        "PE-01 ↔ P-01 by adjusting IGP metrics. Sustained improvement without "
        "capacity addition. Estimated deployment: 30 minutes.\n"
        "  3. Long-term — capacity augment on PE-01 ↔ P-02. 40G → 100G "
        "upgrade. Estimated capex: $180K. Justification: trend analysis shows "
        "this link approaching 80% average utilization over 30 days, "
        "congestion episodes increasing in frequency.\n\n"

        "Please advise on preferred resolution path. Nokia scope is closed on "
        "this incident — no ORCA workaround will be applied. Contact: "
        "orca@noc.operator.example.com for further evidence or telemetry queries.\n\n"

        "— ORCA (on behalf of Nokia NetOps)"
    )
    ts_filename = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return {
        "type":                   "external_tac",
        "tag":                    "tac_handoff_only",
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
            {"filename": "transport-handoff-evidence-summary.yaml",
             "size_bytes": 1840,  "mime_type": "application/yaml", "content_reference": "internal"},
        ],
        "status":                 "sent",
        "triggering_proposal_id": proposal_id,  # None for Act 2 — no proposal exists
    }


ACT2_HANDOFF_LOG = (
    "TAC handoff email auto-sent to transport team · subject: Transport "
    "congestion on PE-01 ↔ P-02 — slice-A enterprise impact, Nokia core cleared"
)


# ── Post-deploy resolution (drafted for human send) ──────────────────

def _validation_table(gates: list) -> str:
    """Render a six-gate validation block for inclusion in email bodies."""
    if not gates:
        return "  (no validation gates recorded)"
    lines = []
    for g in gates:
        status = (g.get("status") or "pending").upper()
        lines.append(f"  {g.get('name','?'):<25} {status:<5} — {g.get('detail','')}")
    return "\n".join(lines)


def build_act1_email(proposal: dict) -> dict:
    ts_detected = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    approve_ts  = proposal.get("approved_at") or _now_iso()
    deploy_ts   = proposal.get("deployed_at") or _now_iso()
    config_pr   = proposal.get("pr_url") or "(config PR pending)"
    config_num  = proposal.get("pr_number")
    episode_pr  = proposal.get("episode_pr_url") or "(episode PR pending)"
    episode_num = proposal.get("episode_pr_number")
    proposal_id = proposal.get("id", "(unknown)")
    approver    = proposal.get("approver") or OPERATOR_PLACEHOLDER
    gates       = proposal.get("validation_gates") or []

    body = (
        f"At {ts_detected}, ORCA detected QER drift on UPF-01 affecting the "
        f"slice-A enterprise cohort (842 accounts, $2.4M ARR). Slice-A priority "
        f"class was enforcing 32 Mbps against a committed GBR of 50 Mbps — a 36% "
        f"shortfall. p99 N3 latency was climbing toward the 15 ms SLA threshold, "
        f"with projected breach in approximately 10 minutes.\n\n"

        f"ORCA composed a single-change restoration: QER update on UPF-01 "
        f"restoring slice-A priority class to the committed GBR of 50 Mbps with "
        f"strict enforcement mode. All six validation gates passed including "
        f"60-second digital twin simulation.\n\n"

        f"Proposal {proposal_id} was approved by {approver} at {approve_ts}. "
        f"Deployment completed in 8 seconds via PFCP Session Modification on "
        f"UPF-01. Config changes committed: see PR {config_pr}"
        f"{' (#' + str(config_num) + ')' if config_num else ''}. "
        f"Full incident episode captured: see PR {episode_pr}"
        f"{' (#' + str(episode_num) + ')' if episode_num else ''}.\n\n"

        f"VALIDATION RESULTS\n{_validation_table(gates)}\n\n"

        f"Post-recovery measurements: slice-A p99 N3 latency recovered from "
        f"13.1 ms to 8.9 ms. Enterprise at-risk cohort reduced from 423 to 14 "
        f"subscribers. Revenue-at-risk reduced by $1.16M. Slice-A SLA headroom "
        f"fully restored. No customer-facing impact occurred — intervention "
        f"landed pre-breach.\n\n"

        f"— ORCA"
    )

    ts_filename = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return {
        "type":                   "internal_ops",
        "tag":                    "post_deploy_resolution",
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


# Scenario id → post-deploy email template factory. Act 2 is NOT here
# — there's no deploy step to fire it after (see build_act2_tac_handoff
# for the email-only flow).
EMAIL_FACTORIES = {
    "slice-a-qos-drift": build_act1_email,
}

# System log entry content used at creation time on deploy.
DRAFTED_SYSTEM_LOG = {
    "slice-a-qos-drift": "NOC notification email drafted · 842 subscriber recovery logged for review",
}
