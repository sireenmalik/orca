"""
agent/customer_intents.py — customer intent loader

Reads customer intent fixtures from ``intents/customers/*.yaml`` once at
process start and exposes three accessors used by the dashboard and the
churn correlator. Every YAML record is treated as opaque dict data — this
module is the *only* place that knows the records came from the
filesystem rather than from a real BSS / TMF921 endpoint.

Production swap path: replace ``_load_filesystem`` with a TMF921 fetcher
(or BSS-API client) that returns the same shape — every caller stays
unchanged. That is the entire point of the indirection.

YAML schema (see intents/customers/cust-*.yaml for examples):

    id: cust-X
    name: ...
    segment: enterprise | strategic | smb
    industry: ...
    headline_use_case: ...
    arr_usd: <int>
    account_exec: ...
    contract: { sla_tier, signed, renewal_date, ... }
    service:
      type: 5g-private-slice | 5g-embb-slice | mpls-l3vpn | optical-wave
      id:   slice-A | l3vpn-... | wave-...
      underlay: LSP-1 | LSP-2 | direct-fiber
    sla_targets: { availability_pct, p99_n3_latency_ms, jitter_ms, ... }
    churn_signals: { previous_nps, recent_nps, ..., health_score }
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

INTENTS_DIR = Path(__file__).resolve().parent.parent / "intents" / "customers"

# ─── Dynamic demo state ──────────────────────────────────────────────────────
# The static YAML fixtures hold each customer's UNDER-FAULT profile (critical
# health, NPS drop, P1 ticket, escalation, etc.) — that is the demo's "money
# shot" state. To make the dashboard arc cleanly through fault → save → reset,
# customers transition between baseline and under-fault dynamically:
#
#   _IMPACTED = {cust-A, ...}  → those customers show their fixture YAML
#                                values (under-fault). All others are bumped
#                                to a baseline (healthy) override.
#   _IMPACTED = set()          → all "dynamic" customers (the ones whose
#                                fixture is an under-fault snapshot) are
#                                bumped to baseline. Customers whose risk is
#                                non-transport (e.g. cust-D's lingering P1)
#                                stay at fixture values regardless.
#
# Lifecycle hooks (called from api/main.py and agent/scenarios.py):
#   /api/demo/reset                 -> clear_impacted()
#   POST /api/scenarios/.../inject  -> set_impacted(scenario.impacted_customers)
#   stream_approval finishes        -> clear_impacted()  (save → baseline)

# Customers whose YAML fixture value is the UNDER-FAULT state — these get
# the baseline override applied when they are NOT in _IMPACTED. Anyone not
# in this set is assumed to have a fixture value that represents their
# steady-state (e.g. cust-D's at-risk story is non-transport, persists).
_DYNAMIC_CUSTOMERS = {"cust-A", "cust-B", "cust-C"}

_IMPACTED: set = set()


def set_impacted(customer_ids) -> None:
    """Mark customers as currently under-fault. They will show their YAML
    fixture (under-fault) values; everyone else gets the baseline override."""
    global _IMPACTED
    _IMPACTED = set(customer_ids or [])


def clear_impacted() -> None:
    """Clear the under-fault marker — return all dynamic customers to
    baseline (healthy) state."""
    global _IMPACTED
    _IMPACTED = set()


def get_impacted() -> set:
    return set(_IMPACTED)


def _apply_state_override(rec: dict) -> dict:
    """Return a possibly-mutated copy of the customer record reflecting
    the current demo state. Static-state customers are returned as-is."""
    cid = rec.get("id")
    if cid not in _DYNAMIC_CUSTOMERS:
        return rec
    if cid in _IMPACTED:
        # Active fault — show the fixture (under-fault) values directly.
        return rec
    # Baseline override: this dynamic customer is currently healthy.
    out = copy.deepcopy(rec)
    cs = out.setdefault("churn_signals", {})
    cs["health_score"] = 92
    # Recover NPS: if the fixture has previous_nps, use that. Otherwise
    # bump current_nps up by 2 minimum.
    prev = cs.get("previous_nps")
    if prev is not None:
        cs["recent_nps"] = prev
    else:
        cs["recent_nps"] = max(cs.get("recent_nps", 7) + 2, 8)
    cs["nps_drop_quarters"] = 0
    cs["open_tickets_p1"] = 0
    cs["latency_complaints_30d"] = 0
    cs["competitor_active"] = False
    cs.pop("recent_escalation", None)
    cs.pop("billing_dispute_open", None)
    cs.pop("resolved_p1_last_90d", None)
    return out


@lru_cache(maxsize=1)
def _load_filesystem() -> dict:
    """Read every cust-*.yaml once. Bad files are skipped, never crash."""
    customers: dict = {}
    skipped: list = []
    if not INTENTS_DIR.exists():
        print(f"[customer_intents] {INTENTS_DIR} missing — 0 fixtures loaded", flush=True)
        return customers
    for path in sorted(INTENTS_DIR.glob("*.yaml")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                rec = yaml.safe_load(fh) or {}
            cid = rec.get("id")
            if not cid:
                skipped.append(f"{path.name}:no-id")
                continue
            customers[cid] = rec
        except Exception as e:
            # never let a malformed fixture take the agent down at boot
            skipped.append(f"{path.name}:{type(e).__name__}")
            continue
    msg = f"[customer_intents] loaded {len(customers)} customer fixtures from {INTENTS_DIR}"
    if skipped:
        msg += f"  (skipped: {', '.join(skipped)})"
    print(msg, flush=True)
    return customers


# ─── Public API ──────────────────────────────────────────────────────────────

def get_customers() -> list:
    """All customer records (with current demo-state overrides applied)."""
    return [_apply_state_override(c) for c in _load_filesystem().values()]


def get_by_id(cust_id: str) -> Optional[dict]:
    """Single customer by id (with current demo-state override applied)."""
    rec = _load_filesystem().get(cust_id)
    return _apply_state_override(rec) if rec else None


def get_by_service(service_id: str) -> list:
    """All customers riding the given service id (slice id, L3VPN id, wave id),
    with current demo-state overrides applied."""
    return [
        _apply_state_override(c) for c in _load_filesystem().values()
        if (c.get("service") or {}).get("id") == service_id
    ]


def reload() -> int:
    """Clear the cache and re-read. For tests and dev. Returns count loaded."""
    _load_filesystem.cache_clear()
    return len(_load_filesystem())
