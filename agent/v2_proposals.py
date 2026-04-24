"""
ORCA v2 Demo — Config Proposals workflow (intent-driven, Git-PR-backed).

Separate from the v1 ``_config_proposals`` store in ``te_agent.py`` — this is
the workflow chassis for the 5G demo and renders a richer card than the v1
Operations tab. The v1 store stays wired to ``/api/config-proposals`` for
the baseline test suite; this module lives behind ``/api/proposals``.

Proposal lifecycle
    pending → approved → deploying → deployed
    pending → rejected

On approve we create a real GitHub PR on a ``v2/cfg/*`` branch so the audit
trail is a real link, then we simulate the device-side deploy (1.5s sleep)
and flip to ``deployed``. The PR is NOT auto-merged — leaves the merge to
the human for demo safety.

All state transitions emit broadcast events on the provided event bus so
the Agent Reasoning Log picks them up.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import base64 as _b64
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional


# In-memory store — populated via POST /api/proposals. Cleared by
# DELETE /api/proposals or /api/demo/reset (so demo reruns are clean).
_proposals: list = []

# Map proposal_id -> True while a deploy is in flight, to guard against
# double-click on Approve & Deploy spawning two PRs.
_deploying: set = set()

GATE_ORDER = [
    "Syntax",
    "Semantic",
    "Mission · utilization",
    "Mission · slice SLA",
    "Digital twin",
    "Policy",
]

GATE_DEFAULT_DETAIL = {
    "Syntax":                "YAML well-formed, schema-valid",
    "Semantic":              "Referenced nodes and slices exist, no dangling references",
    "Mission · utilization": "All link utilization stays under 90% after applying change",
    "Mission · slice SLA":   "Slice SLA thresholds preserved for all affected slices",
    "Digital twin":          "Candidate config applied to twin, 60s traffic simulation passed",
    "Policy":                "Change respects approved intent policies (no manual overrides)",
}


def get_proposals() -> list:
    return list(_proposals)


def clear_proposals() -> None:
    _proposals.clear()
    _deploying.clear()


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _normalize_gates(raw: list) -> list:
    """Fill in default details, order by GATE_ORDER, coerce missing statuses
    to 'pending'. Preserve extras the caller supplied."""
    by_name = {g.get("name"): g for g in (raw or []) if isinstance(g, dict)}
    out = []
    for name in GATE_ORDER:
        g = dict(by_name.get(name) or {})
        g["name"] = name
        g.setdefault("status", "pending")  # pass | fail | pending
        g.setdefault("detail", GATE_DEFAULT_DETAIL[name])
        out.append(g)
    return out


def create_proposal(payload: dict) -> dict:
    """Create a new proposal and append to the store. Returns the created dict."""
    ts = int(time.time() * 1000)
    pid = f"v2-cfg-{ts}"
    p = {
        "id":                     pid,
        "title":                  payload.get("title", "Untitled proposal"),
        "reason":                 payload.get("reason", ""),
        "projected_impact":       payload.get("projected_impact", ""),
        "diff":                   payload.get("diff", []),
        "validation_gates":       _normalize_gates(payload.get("validation_gates", [])),
        "status":                 "pending",
        "created_at":             _now_iso(),
        "approved_at":            None,
        "deployed_at":            None,
        "rejected_at":            None,
        "pr_url":                 None,
        "pr_number":              None,
        "commit_sha":             None,
        "branch":                 None,
        "triggering_incident_id": payload.get("triggering_incident_id"),
        # Optional: scenario id that generated this proposal. Used by
        # _deploy() to stream act-specific recovery log entries after
        # the deploy simulation completes.
        "triggering_scenario_id": payload.get("triggering_scenario_id"),
        # Demo convenience: let the caller pin gates to pass/fail from the
        # UI without re-validating. Real v2 would run checks server-side.
        "all_gates_passed":       all(g.get("status") == "pass"
                                       for g in _normalize_gates(payload.get("validation_gates", []))),
    }
    _proposals.insert(0, p)  # newest-first for the UI
    return p


def _find(proposal_id: str) -> Optional[dict]:
    return next((p for p in _proposals if p.get("id") == proposal_id), None)


async def _github_pr(proposal: dict) -> dict:
    """Create a real PR on sireenmalik/orca against main, with a
    v2/cfg/<slug>-<ts> branch prefix. Returns {pr_number, pr_url,
    commit_sha, branch} on success, or {error} on failure. Never raises —
    a failed PR call shouldn't kill the demo's approve flow."""
    token = os.getenv("GITHUB_TOKEN", "")
    owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo  = os.getenv("GITHUB_REPO",  "orca")
    if not token:
        return {"error": "GITHUB_TOKEN not set"}

    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
        "Content-Type":  "application/json",
    }
    base_url = f"https://api.github.com/repos/{owner}/{repo}"

    def _call(method: str, path: str, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(f"{base_url}{path}", data=body,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode() or "{}"), r.status
        except urllib.error.HTTPError as e:
            try:   return json.loads(e.read().decode() or "{}"), e.code
            except Exception: return {"message": "http error"}, e.code

    slug_src = (proposal.get("title") or "cfg").lower()
    slug = "".join(ch if ch.isalnum() else "-" for ch in slug_src).strip("-")[:40] or "cfg"
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    branch = f"v2/cfg/{slug}-{ts}"

    # Get main SHA
    ref, _ = _call("GET", "/git/ref/heads/main")
    main_sha = (ref or {}).get("object", {}).get("sha", "")
    if not main_sha:
        return {"error": "cannot read main ref"}

    # Branch from main
    _call("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": main_sha})

    # Commit a candidate YAML with the diff (conceptual — not real NETCONF).
    diff_block = "\n".join(
        ("  " if d.get("type") == "context" else
         "- " if d.get("type") == "remove" else
         "+ ") + str(d.get("line", ""))
        for d in (proposal.get("diff") or [])
    ) or "  # empty diff"
    gates_block = "\n".join(
        f"  - name: \"{g.get('name')}\"\n    status: \"{g.get('status')}\"\n    detail: \"{g.get('detail','')}\""
        for g in (proposal.get("validation_gates") or [])
    )
    yaml = (
        f"# ORCA v2 config proposal — {proposal.get('id')}\n"
        f"# Auto-generated on approve. Branch: {branch}\n\n"
        f"title: \"{proposal.get('title','')}\"\n"
        f"reason: |\n  {proposal.get('reason','').strip()}\n"
        f"projected_impact: |\n  {proposal.get('projected_impact','').strip()}\n"
        f"triggering_incident_id: \"{proposal.get('triggering_incident_id') or ''}\"\n"
        f"validation_gates:\n{gates_block}\n"
        f"diff: |\n{diff_block}\n"
    )
    file_path = f"config_mgmt/candidate/v2-5g/{proposal.get('id')}.yaml"

    put, put_status = _call("PUT", f"/contents/{file_path}", {
        "message": f"v2 cfg proposal: {proposal.get('title','')}",
        "content": _b64.b64encode(yaml.encode()).decode(),
        "branch":  branch,
    })
    commit_sha = (put or {}).get("commit", {}).get("sha", "") if put_status in (200, 201) else ""

    # Open PR against main (leave open — human merges, not us)
    pr_body = (
        "## 🧠 ORCA v2 config proposal\n\n"
        "> Auto-generated from the Operations tab. Approval was given by a human "
        "operator in the ORCA dashboard; this PR captures the change for audit.\n\n"
        f"**Reason**\n\n{proposal.get('reason','')}\n\n"
        f"**Projected impact**\n\n{proposal.get('projected_impact','')}\n\n"
        f"**Validation gates**\n\n" +
        "\n".join(
            f"- {'✅' if g.get('status')=='pass' else '❌' if g.get('status')=='fail' else '⏳'} "
            f"**{g.get('name')}** — {g.get('detail','')}"
            for g in (proposal.get("validation_gates") or [])
        ) +
        f"\n\n**Candidate config**: `{file_path}`\n"
        f"\n*Triggering incident:* `{proposal.get('triggering_incident_id') or '—'}`\n"
    )
    pr_data, pr_status = _call("POST", "/pulls", {
        "title": f"v2/cfg: {proposal.get('title','')} [{ts}]",
        "body":  pr_body,
        "head":  branch,
        "base":  "main",
    })
    if pr_status not in (200, 201):
        return {"error": f"PR creation failed ({pr_status}): {pr_data}"}
    return {
        "pr_number":  pr_data.get("number"),
        "pr_url":     pr_data.get("html_url"),
        "commit_sha": commit_sha,
        "branch":     branch,
    }


async def approve_proposal(
    proposal_id: str,
    broadcast: Callable[[dict], Awaitable[None]],
) -> dict:
    """Run the approve → deploy flow. ``broadcast`` is an async callable
    (typically ``ConnectionManager.broadcast``) used to post reasoning-log
    events. Returns the final proposal state."""
    p = _find(proposal_id)
    if not p:
        return {"error": "not found"}
    if p["status"] not in ("pending",):
        return {"error": f"cannot approve from status '{p['status']}'"}
    # Dedup guard — second approve click while deploy is in flight.
    if proposal_id in _deploying:
        return {"status": "already_deploying", "proposal_id": proposal_id}
    if not all(g.get("status") == "pass" for g in p.get("validation_gates") or []):
        return {"error": "cannot deploy — one or more validation gates failed"}
    _deploying.add(proposal_id)

    p["status"]      = "approved"
    p["approved_at"] = _now_iso()
    await broadcast({
        "type": "agent_status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "status":  "proposal_approved",
            "message": f"✅ {p['id']} approved by operator — spawning deploy",
        },
    })

    # Fire-and-forget the rest so the HTTP response can return quickly.
    asyncio.create_task(_deploy(p, broadcast))
    return dict(p)


async def _deploy(p: dict, broadcast) -> None:
    try:
        # ── 1. Open the audit PR ──
        p["status"] = "deploying"
        await broadcast({
            "type": "agent_status",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "status":  "deploying",
                "message": f"⚙️  {p['id']} deploying — opening audit PR on sireenmalik/orca",
            },
        })

        pr_info = await _github_pr(p)
        if pr_info.get("error"):
            await broadcast({
                "type": "tool_error",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "tool":  "github.pulls",
                    "error": pr_info["error"],
                },
            })
        else:
            p["pr_number"]  = pr_info.get("pr_number")
            p["pr_url"]     = pr_info.get("pr_url")
            p["branch"]     = pr_info.get("branch")
            p["commit_sha"] = pr_info.get("commit_sha")
            await broadcast({
                "type": "pr_opened",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "pr_number": p["pr_number"],
                    "pr_url":    p["pr_url"],
                    "message":   f"🔀 PR #{p['pr_number']} opened — {p['pr_url']}",
                },
            })

        # ── 2. Simulated device-side deploy ──
        #
        # Real v2 would stream NETCONF/PFCP commits per affected device.
        # Here we sleep ~1.5s so the "Deploying..." state is visible on
        # stage, then emit a confirming log entry.
        await asyncio.sleep(1.5)

        p["status"]      = "deployed"
        p["deployed_at"] = _now_iso()
        await broadcast({
            "type": "agent_status",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "status":  "deployed",
                "message": (
                    f"✅ {p['id']} deployed — "
                    f"{'PR #' + str(p['pr_number']) if p.get('pr_number') else 'no PR'} · "
                    f"{p.get('branch','(no branch)')}"
                ),
            },
        })

        # ── Act-specific post-deploy recovery stream ──
        # Only when the proposal came from a scripted scenario. Uses the
        # "recovered" subtype for green styling, distinct from reasoning.
        scenario_id = p.get("triggering_scenario_id")
        if scenario_id:
            from agent.scenarios import SCENARIO_RECOVERY_ENTRIES
            for entry in SCENARIO_RECOVERY_ENTRIES.get(scenario_id, []):
                await asyncio.sleep(entry.get("delay_ms", 300) / 1000.0)
                await broadcast({
                    "type":      "scenario_log",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "seq":           -2,
                        "subtype":       "recovered",
                        "content":       entry.get("content", ""),
                        "is_conclusion": False,
                        "scenario_id":   scenario_id,
                        "proposal_id":   p["id"],
                    },
                })
    finally:
        _deploying.discard(p["id"])


async def reject_proposal(
    proposal_id: str,
    broadcast: Callable[[dict], Awaitable[None]],
    comment: str = "",
) -> dict:
    p = _find(proposal_id)
    if not p:
        return {"error": "not found"}
    if p["status"] not in ("pending",):
        return {"error": f"cannot reject from status '{p['status']}'"}
    p["status"]      = "rejected"
    p["rejected_at"] = _now_iso()
    if comment:
        p["rejection_comment"] = comment
    await broadcast({
        "type": "agent_status",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "status":  "proposal_rejected",
            "message": f"✗ {p['id']} rejected by operator" + (f" — {comment}" if comment else ""),
        },
    })
    return dict(p)
