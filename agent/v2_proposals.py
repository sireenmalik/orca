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
        "summary":                payload.get("summary", ""),
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
        # v2 modal — per-device diff + per-device final config for the
        # three-column review layout. If a scenario template doesn't
        # supply these, the modal falls back to the flat `diff` field.
        "devices":                list(payload.get("devices", []))        or None,
        "device_diffs":           dict(payload.get("device_diffs", {}))   or None,
        "device_configs":         dict(payload.get("device_configs", {})) or None,
        # Modal action-bar state
        "comment":                "",
        "reviewed_at":            None,
        # Demo convenience: let the caller pin gates to pass/fail from the
        # UI without re-validating. Real v2 would run checks server-side.
        "all_gates_passed":       all(g.get("status") == "pass"
                                       for g in _normalize_gates(payload.get("validation_gates", []))),
    }
    _proposals.insert(0, p)  # newest-first for the UI
    return p


def _find(proposal_id: str) -> Optional[dict]:
    return next((p for p in _proposals if p.get("id") == proposal_id), None)


def _gh_call(method: str, path: str, token: str, data=None):
    """Stdlib GitHub API helper used by both config PR + episode PR paths."""
    owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo  = os.getenv("GITHUB_REPO",  "orca")
    url = f"https://api.github.com/repos/{owner}/{repo}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode() or "{}"), r.status
    except urllib.error.HTTPError as e:
        try:   return json.loads(e.read().decode() or "{}"), e.code
        except Exception: return {"message": "http error"}, e.code


# Scenario id → recovery metrics table used in the episode PR body
# + post-deploy email. Matches what the Churn Forecast tab animates to
# for Act 1; Act 2 is transport-narrative-focused (no churn delta).
EPISODE_RECOVERY_METRICS = {
    "slice-a-qos-drift": [
        ("slice-A p99 N3 latency",    "13.1 ms",   "8.9 ms"),
        ("enterprise at-risk cohort", "423 subs",  "14 subs"),
        ("revenue-at-risk",           "$1.20M",    "$40K"),
        ("slice-A SLA headroom",      "0.1 ms",    "6.1 ms"),
    ],
    "transport-congestion-upf-innocent": [
        ("slice-A p99 N3 latency",    "14.0 ms",   "9.1 ms (via alternate path)"),
        ("LSP-1 utilization",         "93%",       "93% (unchanged — upstream)"),
        ("alternate path util",       "24%",       "61% (absorbed migration)"),
        ("Nokia core impact",         "—",         "contained, zero customer-facing"),
    ],
}

# Scenario id → concise diagnosis summary for the episode PR body
EPISODE_DIAGNOSIS_SUMMARY = {
    "slice-a-qos-drift": (
        "Pre-threshold detection engaged as slice-A p99 N3 latency on UPF-01 "
        "climbed from 11.2 ms toward the 15 ms SLA threshold. QER-table audit "
        "revealed enforcement on the slice-A priority class drifted to 32 Mbps "
        "vs 50 Mbps committed GBR (-36%), accumulated from successive config "
        "changes. Single root cause localized. Fix: one atomic QER restoration "
        "bringing enforcement back to committed intent with strict mode."
    ),
    "transport-congestion-upf-innocent": (
        "Slice-A p99 N3 latency climbing on UPF-01. UPF-01 local resources "
        "(CPU, memory, PFCP association, QER) cleared as cause. SMF / AMF "
        "signaling plane clean. Scope expanded to transport: LSP-1 path "
        "PE-01 → P-02 → PE-03 showed 93% utilization on PE-01 ↔ P-02 with "
        "microbursts. Nokia core is innocent; root cause is transport-layer "
        "congestion upstream of UPF-01."
    ),
}


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


async def _github_episode_pr(proposal: dict) -> dict:
    """Create the audit-trail episode PR on a v2/episodes/* branch.
    Commits an episode YAML capturing the full incident-to-resolution
    arc (diagnosis, validation, approver, recovery). Links back to the
    config PR in its body. Returns {pr_number, pr_url, branch, commit_sha}
    on success, or {error: ...} on failure. Never raises."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return {"error": "GITHUB_TOKEN not set"}

    scenario_id = proposal.get("triggering_scenario_id") or proposal.get("triggering_incident_id") or "scenario"
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    branch = f"v2/episodes/{scenario_id}-{ts}"

    ref, _ = _gh_call("GET", "/git/ref/heads/main", token)
    main_sha = (ref or {}).get("object", {}).get("sha", "")
    if not main_sha:
        return {"error": "cannot read main ref"}
    _gh_call("POST", "/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": main_sha})

    # Episode YAML — captures the full arc. Deliberately minimal — the
    # PR body is where the human-readable version lives.
    gates = proposal.get("validation_gates") or []
    metrics_rows = EPISODE_RECOVERY_METRICS.get(scenario_id, [])
    ep_yaml = (
        f"# ORCA v2 incident episode — {proposal.get('id')}\n"
        f"# Scenario: {scenario_id}\n\n"
        f"proposal_id: \"{proposal.get('id','')}\"\n"
        f"triggering_scenario: \"{scenario_id}\"\n"
        f"detected_at: \"{proposal.get('created_at','')}\"\n"
        f"approved_at: \"{proposal.get('approved_at','')}\"\n"
        f"deployed_at: \"{proposal.get('deployed_at','')}\"\n"
        f"approver: \"{proposal.get('approver') or 'operator@session'}\"\n"
        f"config_pr_url: \"{proposal.get('pr_url') or ''}\"\n"
        f"config_pr_number: {proposal.get('pr_number') or 'null'}\n\n"
        f"diagnosis_summary: |\n  {EPISODE_DIAGNOSIS_SUMMARY.get(scenario_id, '')}\n\n"
        f"validation_results:\n"
        + "\n".join(
            f"  - name: \"{g.get('name')}\"\n"
            f"    status: \"{g.get('status')}\"\n"
            f"    detail: \"{g.get('detail','')}\""
            for g in gates
        )
        + "\n\nrecovery_metrics:\n"
        + "\n".join(f"  - metric: \"{m[0]}\"\n    before: \"{m[1]}\"\n    after: \"{m[2]}\"" for m in metrics_rows)
        + "\n"
    )
    ep_path = f"v2-demo/episodes/{scenario_id}-{ts}.yaml"
    _gh_call("PUT", f"/contents/{ep_path}", token, {
        "message": f"v2 episode: {proposal.get('title','')}",
        "content": _b64.b64encode(ep_yaml.encode()).decode(),
        "branch":  branch,
    })

    # Build the PR body — markdown, includes the config PR backlink and
    # the validation / metrics tables the post-deploy email references.
    cfg_pr = proposal.get("pr_url") or "(config PR unknown)"
    cfg_num = proposal.get("pr_number") or "?"
    approver = proposal.get("approver") or "operator@session"
    approved = proposal.get("approved_at") or "—"
    detected = proposal.get("created_at") or "—"

    gates_md = "\n".join(
        f"| {g.get('name')} | {'✅ PASS' if g.get('status') == 'pass' else '❌ FAIL' if g.get('status') == 'fail' else '⏳ PENDING'} | {g.get('detail','')} |"
        for g in gates
    )
    metrics_md = "\n".join(f"| {m[0]} | {m[1]} | {m[2]} |" for m in metrics_rows)

    body_md = (
        f"## 📖 ORCA v2 episode — {proposal.get('title','')}\n\n"
        f"> Auto-generated by ORCA after the incident-to-resolution arc "
        f"completed. Captures the full audit trail. Corresponds to config "
        f"PR #{cfg_num}.\n\n"
        f"**Triggering scenario**: `{scenario_id}`  \n"
        f"**Detected at**: `{detected}`  \n"
        f"**Approved at**: `{approved}`  \n"
        f"**Approver**: `{approver}`\n\n"
        f"**Resolved by config PR #{cfg_num}** · {cfg_pr}\n\n"
        f"### Diagnosis summary\n\n"
        f"{EPISODE_DIAGNOSIS_SUMMARY.get(scenario_id, '(no diagnosis summary available)')}\n\n"
        f"### Validation results\n\n"
        f"| Gate | Status | Detail |\n"
        f"|------|--------|--------|\n"
        f"{gates_md}\n\n"
        f"### Recovery metrics\n\n"
        f"| Metric | Before | After |\n"
        f"|--------|--------|-------|\n"
        f"{metrics_md}\n\n"
        f"---\n\n"
        f"*Episode committed automatically. Config + episode together comprise "
        f"the full audit trail for this incident.*\n"
    )

    pr_data, pr_status = _gh_call("POST", "/pulls", token, {
        "title": f"v2/episode: {proposal.get('title','')} — {datetime.utcnow().strftime('%Y-%m-%d')}",
        "body":  body_md,
        "head":  branch,
        "base":  "main",
    })
    if pr_status not in (200, 201):
        return {"error": f"episode PR creation failed ({pr_status}): {pr_data}"}

    return {
        "pr_number":  pr_data.get("number"),
        "pr_url":     pr_data.get("html_url"),
        "branch":     branch,
    }


async def _github_patch_config_pr_with_episode_link(config_pr_number, episode_pr_number, episode_pr_url):
    """Append a backlink to the episode PR onto the config PR body so
    the two PRs cross-reference each other. Read-modify-write."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token or not config_pr_number:
        return False
    current, status = _gh_call("GET", f"/pulls/{config_pr_number}", token)
    if status != 200:
        return False
    existing_body = current.get("body") or ""
    addendum = (
        f"\n\n---\n\n"
        f"📖 **Episode captured**: See [PR #{episode_pr_number}]({episode_pr_url}) "
        f"for full incident context.\n"
    )
    if f"PR #{episode_pr_number}" in existing_body:
        return True  # idempotent — already backlinked
    patched, patch_status = _gh_call("PATCH", f"/pulls/{config_pr_number}", token, {
        "body": existing_body + addendum,
    })
    return patch_status == 200


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

            # ── Act 1 only: flip Churn Forecast to the recovered state ──
            # Act 2 is a transport workaround, not a revenue recovery, so
            # it intentionally does NOT update churn metrics. Keeping the
            # two acts' narratives cleanly separated: Act 1 = revenue
            # protected; Act 2 = Nokia TAC handoff.
            if scenario_id == "slice-a-qos-drift":
                from agent import churn_state
                new_state = churn_state.trigger_slice_a_recovery()
                await broadcast({
                    "type":      "churn_updated",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "phase":            new_state.get("phase"),
                        "transitioned_at":  new_state.get("transitioned_at"),
                        "triggered_by":     scenario_id,
                        "proposal_id":      p["id"],
                    },
                })

            # ── Episode PR (v2/episodes/* branch) — second audit PR ─────
            # After the config PR and deploy simulation are both complete,
            # commit a companion episode that captures the full arc and
            # links to the config PR. Update the config PR body with a
            # backlink so the two cross-reference.
            p["approver"] = p.get("approver") or "operator@session"
            episode = await _github_episode_pr(p)
            if not episode.get("error"):
                p["episode_pr_number"] = episode.get("pr_number")
                p["episode_pr_url"]    = episode.get("pr_url")
                p["episode_branch"]    = episode.get("branch")
                await broadcast({
                    "type":      "pr_opened",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "pr_number": episode.get("pr_number"),
                        "pr_url":    episode.get("pr_url"),
                        "message":   f"📖 Episode PR #{episode.get('pr_number')} opened — {episode.get('pr_url')}",
                    },
                })
                await broadcast({
                    "type":      "scenario_log",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "seq":           -4,
                        "subtype":       "system",
                        "content":       f"Episode committed to Git · PR #{episode.get('pr_number')} · linked to config PR #{p.get('pr_number')}",
                        "is_conclusion": False,
                        "scenario_id":   scenario_id,
                        "proposal_id":   p["id"],
                    },
                })
                # Cross-link: patch the config PR body with the episode
                # backlink. Best-effort — a GitHub blip here is harmless.
                try:
                    await _github_patch_config_pr_with_episode_link(
                        p.get("pr_number"), episode.get("pr_number"), episode.get("pr_url")
                    )
                except Exception:
                    pass
            else:
                await broadcast({
                    "type":      "tool_error",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {"tool": "github.episode_pr", "error": episode["error"]},
                })

            # ── Draft the matching outbound resolution email (Act 1 NOC /
            # Act 2 TAC). Happens 500ms after the 'deployed' broadcast so
            # the state-transition pulse on the card lands first. Email
            # is a DRAFT — operator clicks Send to dispatch. Contains the
            # approver identity, both PR links, validation table, and
            # recovery metrics (built into the template).
            from agent import v2_emails
            factory   = v2_emails.EMAIL_FACTORIES.get(scenario_id)
            log_line  = v2_emails.DRAFTED_SYSTEM_LOG.get(scenario_id)
            if factory:
                await asyncio.sleep(0.5)
                drafted = v2_emails.create(factory(p))
                await broadcast({
                    "type":      "email_created",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {
                        "id":                     drafted["id"],
                        "type":                   drafted["type"],
                        "subject":                drafted["subject"],
                        "tag":                    drafted.get("tag"),
                        "triggering_proposal_id": p["id"],
                    },
                })
                if log_line:
                    await broadcast({
                        "type":      "scenario_log",
                        "timestamp": datetime.utcnow().isoformat(),
                        "data": {
                            "seq":           -3,
                            "subtype":       "system",
                            "content":       log_line,
                            "is_conclusion": False,
                            "scenario_id":   scenario_id,
                            "proposal_id":   p["id"],
                            "email_id":      drafted["id"],
                        },
                    })
    finally:
        _deploying.discard(p["id"])


def save_edits(proposal_id: str, payload: dict) -> dict:
    """Save & Commit — write edited comment / device_configs / reason /
    diff back to the proposal. Keeps status=pending; sets reviewed_at."""
    p = _find(proposal_id)
    if not p:
        return {"error": "not found"}
    if p["status"] != "pending":
        return {"error": f"cannot save in status '{p['status']}'"}
    if "comment" in payload:
        p["comment"] = payload["comment"] or ""
    if "reason" in payload:
        p["reason"] = payload["reason"] or ""
    if "device_configs" in payload and isinstance(payload["device_configs"], dict):
        p["device_configs"] = {**(p.get("device_configs") or {}), **payload["device_configs"]}
    if "diff" in payload and isinstance(payload["diff"], list):
        p["diff"] = payload["diff"]
    p["reviewed_at"] = _now_iso()
    return dict(p)


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
