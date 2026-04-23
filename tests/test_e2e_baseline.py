"""
ORCA Baseline E2E Tests — v1.0.0
=================================

Pins the three use cases + operational invariants from docs/ORCA-SPEC.md.
Requires a running ORCA instance; target is set via the ORCA_BASE_URL
env var, defaulting to http://localhost (the docker-compose binding on
port 80). The ANTHROPIC_API_KEY + GITHUB_TOKEN must already be in the
container's env — these tests don't stub them.

Run locally:
    ORCA_BASE_URL=http://localhost pytest tests/test_e2e_baseline.py -v -s

Run against the demo droplet:
    ORCA_BASE_URL=http://157.230.174.132 pytest tests/test_e2e_baseline.py -v -s

These tests reset live state between cases via /api/demo/reset and
/api/demo/security-reset and DELETE /api/emails, /api/config-proposals,
/api/security-alerts. Don't point them at anything you care about.

Timings: LLM analyze cycles take ~30-45s on Claude Sonnet 4.x.
stream_approval takes ~12-18s. Total suite ~3-5 min.
"""
import json
import os
import time

import pytest
import urllib.request
import urllib.error


BASE = os.environ.get("ORCA_BASE_URL", "http://localhost").rstrip("/")

# Polling budgets — generous because we're waiting on a real LLM.
ANALYZE_TIMEOUT_S = 75
STREAM_APPROVAL_TIMEOUT_S = 30
POLL_INTERVAL_S = 2
# Per-request timeout — when the agent is mid-cycle the FastAPI event loop
# can stall briefly, so be patient.
HTTP_TIMEOUT_S = 60


# ── Tiny HTTP helper (stdlib only so this works in any env) ──────────

def _req(method, path, body=None, timeout=HTTP_TIMEOUT_S):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    # Retry once on transient timeout — can happen when the FastAPI event
    # loop is mid-LLM-call. Not for HTTPError (those are deterministic).
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
                return (r.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return (e.code, json.loads(e.read().decode() or "{}"))
        except (TimeoutError, urllib.error.URLError):
            if attempt == 1:
                raise
            time.sleep(2)


def get(path):  return _req("GET", path)
def post(path, body=None): return _req("POST", path, body if body is not None else {})
def delete(path): return _req("DELETE", path)


def _wait_for(check, timeout, interval=POLL_INTERVAL_S, msg=""):
    """Poll `check()` until it returns truthy or timeout. Returns the
    last value seen (so tests can inspect what was found)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = check()
        if last:
            return last
        time.sleep(interval)
    pytest.fail(f"timeout after {timeout}s waiting for: {msg}\nlast seen: {last!r}")


# ── Shared reset ─────────────────────────────────────────────────────

@pytest.fixture
def clean_state():
    """Reset everything before each E2E test. Stop any running autonomous
    agent first — otherwise its 15-second poll loop kicks in mid-test and
    emits events / creates proposals we didn't ask for, causing flakiness."""
    post("/api/agent/stop")
    time.sleep(1)
    post("/api/demo/reset")
    post("/api/demo/security-reset")
    delete("/api/emails")
    delete("/api/config-proposals")
    delete("/api/security-alerts")
    # Give the backend a moment to broadcast cleared state
    time.sleep(2)
    yield
    # Teardown: stop the agent again so the loop isn't running between tests
    post("/api/agent/stop")


# ── Preconditions ────────────────────────────────────────────────────

def test_health_endpoint_reachable():
    """The service must be up; all other tests depend on this."""
    status, body = get("/api/health")
    assert status == 200, f"/api/health returned {status}"
    assert body.get("status") == "ok"
    assert body.get("service") == "ORCA"


def test_churn_risk_schema(clean_state):
    """/api/churn-risk must return an `lsp_id` inside each risk object
    (else ChurnTab's .map key is undefined and React drops the row)."""
    status, body = get("/api/churn-risk")
    assert status == 200
    risks = body.get("risks", {})
    assert len(risks) >= 2, f"expected at least 2 customer LSPs, got {list(risks)}"
    for lsp_id, r in risks.items():
        assert r.get("lsp_id") == lsp_id, \
            f"risk object for {lsp_id} missing 'lsp_id' field (ChurnTab will blank)"
        assert "churn_probability_pct" in r
        assert "risk_band" in r
        assert "arr_usd" in r


# ── Use Case 1: LSP reroute → propose → approve → PR → email 3 ──────

def test_use_case_1_full_flow(clean_state):
    """Inject fault → agent analyzes → proposal created with util data →
    approve → PR opened → Config Deployed email queued → episode written
    with PR cross-reference."""
    # 1. Inject fault
    status, body = post("/api/demo/inject-failure", {"link_id": "R1-R4"})
    assert status == 200 and body.get("success"), body
    assert body.get("state") == "down"

    # 2. Trigger analyze (don't rely on poll loop — tests shouldn't be flaky)
    status, body = post("/api/agent/analyze", {
        "context": (
            "CRITICAL: R1-R4 DOWN. Reroute affected LSPs, then call "
            "propose_config_change to stage permanent IGP metric changes, "
            "then open_pull_request, then write_episode."
        )
    })
    assert status == 200

    # 3. Wait for proposal to appear
    def has_proposal():
        s, b = get("/api/config-proposals")
        if s != 200: return None
        props = b.get("proposals", [])
        return props[-1] if props else None

    proposal = _wait_for(has_proposal, ANALYZE_TIMEOUT_S, msg="proposal to be created")
    assert proposal, "no proposal created"

    # 4. Proposal must have all v1.0.0 baseline fields
    assert proposal.get("id", "").startswith("cfg-")
    assert proposal.get("status") == "pending"
    assert proposal.get("title"), "title missing"
    assert proposal.get("reason"), "reason missing"

    vchecks = proposal.get("validation_checks", {})
    vdetail = proposal.get("validation_detail", {})
    for k in ("syntax", "semantic", "mission_1", "mission_2", "digital_twin", "policy"):
        assert k in vchecks, f"validation_checks missing {k}"
        assert k in vdetail, f"validation_detail missing {k}"
        assert isinstance(vchecks[k], bool), f"{k} must be bool not {type(vchecks[k])}"

    # 5. Changes must use the `device` key (invariant B)
    changes = proposal.get("changes", [])
    assert changes, "proposal has no changes"
    for ch in changes:
        assert "device" in ch, \
            f"change missing 'device' key (has keys {list(ch)}) — breaks stream_approval router extraction"

    # 6. util_before / util_after must be captured (invariant C)
    util_before = proposal.get("util_before", {})
    util_after = proposal.get("util_after", {})
    assert util_before, "util_before snapshot missing — analyze() didn't populate _util_before_snapshot"
    assert util_after, "util_after snapshot missing"
    assert "max_util_before" in proposal
    assert "max_util_after" in proposal

    # 7. Approve and wait for PR + email 3
    proposal_id = proposal["id"]
    status, body = post(f"/api/config-proposals/{proposal_id}/approved")
    assert status == 200 and body.get("success"), body

    def deploy_email_arrived():
        s, b = get("/api/emails")
        if s != 200: return None
        for e in b.get("emails", []):
            subj = e.get("subject", "")
            if "ORCA Config Deployed" in subj and "PR #" in subj:
                return subj
        return None

    deploy_subj = _wait_for(
        deploy_email_arrived, STREAM_APPROVAL_TIMEOUT_S,
        msg="'ORCA Config Deployed' email",
    )
    # Must contain a real PR number, not "?" or empty
    assert "PR #" in deploy_subj
    pr_part = deploy_subj.split("PR #", 1)[1]
    pr_num_str = pr_part.split()[0].rstrip("|").strip()
    assert pr_num_str.isdigit(), f"PR number not populated in subject: {deploy_subj!r}"


def test_idempotent_approve_invariant_E(clean_state):
    """Approving the same proposal twice must not spawn stream_approval
    twice — no duplicate PRs, no duplicate Config Deployed emails."""
    post("/api/demo/inject-failure", {"link_id": "R1-R4"})
    post("/api/agent/analyze", {
        "context": "R1-R4 DOWN. Reroute then propose_config_change then write_episode.",
    })

    def has_proposal():
        s, b = get("/api/config-proposals")
        props = b.get("proposals", []) if s == 200 else []
        return props[-1] if props else None

    proposal = _wait_for(has_proposal, ANALYZE_TIMEOUT_S, msg="proposal")
    pid = proposal["id"]

    # Fire two approves back-to-back
    s1, r1 = post(f"/api/config-proposals/{pid}/approved")
    s2, r2 = post(f"/api/config-proposals/{pid}/approved")

    assert s1 == 200 and s2 == 200
    assert r1.get("status") == "approved", r1
    assert r2.get("status") == "already_deploying", \
        f"second approve must be guarded, got {r2}"

    # Wait for stream_approval to finish, then count Config Deployed emails
    time.sleep(STREAM_APPROVAL_TIMEOUT_S)
    s, b = get("/api/emails")
    deployed = [e for e in b.get("emails", [])
                if "ORCA Config Deployed" in e.get("subject", "")]
    assert len(deployed) == 1, \
        f"expected exactly one 'Config Deployed' email, got {len(deployed)}: " \
        f"{[e.get('subject') for e in deployed]}"


# ── Use Case 2: Security rogue config → revert → remediated ──────────

def test_use_case_2_security_flow(clean_state):
    """Rogue config → agent detects → NOC + TAC emails fire → revert
    proposal with security flag → approve → remediation PR → alert
    flipped to `remediated` with PR attached."""
    # 1. Inject rogue
    status, body = post("/api/demo/inject-rogue-config")
    assert status == 200 and body.get("success"), body
    assert len(body.get("changes", [])) >= 1, "rogue changes not staged"

    # Provisional alert must appear immediately (no Analyze needed)
    s, b = get("/api/security-alerts")
    assert s == 200
    assert len(b.get("alerts", [])) >= 1, "provisional security alert not raised"

    # 2. Trigger analyze to run full security handler
    post("/api/agent/analyze", {
        "context": (
            "SECURITY: config drift alarm on R1. Call detect_config_drift "
            "then raise_security_alert to archive evidence, create a revert "
            "proposal, and notify NOC + TAC."
        ),
    })

    # 3. Wait for revert proposal
    def has_security_proposal():
        s, b = get("/api/config-proposals")
        if s != 200: return None
        for p in b.get("proposals", []):
            title_lc = (p.get("title", "") or "").lower()
            if ("security" in title_lc or "revert" in title_lc
                    or p.get("security")):
                return p
        return None

    revert = _wait_for(has_security_proposal, ANALYZE_TIMEOUT_S,
                      msg="security revert proposal")

    # Revert must carry rogue→baseline diff on R1
    changes = revert.get("changes", [])
    assert changes, "revert proposal has no changes"
    targets = {ch.get("device") for ch in changes}
    assert "R1" in targets, f"revert must target R1, got {targets}"

    # 4. NOC + TAC emails must both be queued (invariant F)
    s, b = get("/api/emails")
    subjects = [e.get("subject", "") for e in b.get("emails", [])]
    noc = [s for s in subjects if "SECURITY" in s.upper()
           and "TAC" not in s.upper()]
    tac = [s for s in subjects if "[TAC P1]" in s.upper()
           or "TAC P1" in s.upper()]
    assert noc, f"NOC security email missing from {subjects}"
    assert tac, f"TAC P1 email missing from {subjects}"

    # 5. Approve revert → expect remediation PR + alert remediated
    rid = revert["id"]
    s, _ = post(f"/api/config-proposals/{rid}/approved")
    assert s == 200

    # 6. Alert status must flip to `remediated` (invariant G)
    def alert_remediated():
        s, b = get("/api/security-alerts")
        if s != 200: return None
        for a in b.get("alerts", []):
            if a.get("status") == "remediated":
                return a
        return None

    remediated = _wait_for(alert_remediated, STREAM_APPROVAL_TIMEOUT_S,
                          msg="security alert flipped to remediated")
    assert remediated.get("node") == "R1"
    assert remediated.get("remediation_pr_number"), \
        "remediated alert must carry a PR number"


# ── Use Case 3: Churn KPIs react to live data ────────────────────────

def test_use_case_3_churn_live_shape(clean_state):
    """After a fault is active, /api/churn-risk must include reroute/
    breach counters that the dashboard uses to derive the live KPIs."""
    # Baseline read
    s, b = get("/api/churn-risk")
    assert s == 200
    baseline = b["risks"]

    # Inject fault — churn probability for affected LSPs should eventually rise
    post("/api/demo/inject-failure", {"link_id": "R1-R4"})

    s, b = get("/api/churn-risk")
    assert s == 200
    under_fault = b["risks"]
    assert set(under_fault.keys()) == set(baseline.keys()), \
        "LSP set should stay stable across states"

    # Each risk object has the full fieldset used by the dashboard
    for lsp_id, r in under_fault.items():
        for k in ("customer", "segment", "arr_usd", "risk_score",
                  "risk_band", "churn_probability_pct", "reroute_count",
                  "breach_90_count", "time_degraded_mins", "lsp_id"):
            assert k in r, f"{lsp_id} missing churn field {k}"


# ── Operational: agent tool surface is stable ────────────────────────

def test_agent_state_endpoint_stable(clean_state):
    """/api/state returns nodes, links, lsps, alarms — the contract the
    WebSocket also uses. The 3 LSPs from the spec must be present."""
    s, b = get("/api/state")
    assert s == 200
    assert set(b.keys()) >= {"nodes", "links", "lsps", "alarms"}
    assert len(b["nodes"]) == 6, "expected 6-node ring"
    assert set(b["lsps"].keys()) == {"lsp-customer-a", "lsp-customer-b", "lsp-mgmt"}
