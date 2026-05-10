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

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

INTENTS_DIR = Path(__file__).resolve().parent.parent / "intents" / "customers"


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
    """All customer records, list of dicts. Caller filters as needed."""
    return list(_load_filesystem().values())


def get_by_id(cust_id: str) -> Optional[dict]:
    """Single customer by id, or None if not found."""
    return _load_filesystem().get(cust_id)


def get_by_service(service_id: str) -> list:
    """All customers riding the given service id (slice id, L3VPN id, wave id).

    Generalises the earlier get_by_slice — the schema's `service.id` field
    holds whichever string identifies the service for that customer's
    domain (5G slice, MPLS L3VPN instance, or optical wavelength).
    """
    return [
        c for c in _load_filesystem().values()
        if (c.get("service") or {}).get("id") == service_id
    ]


def reload() -> int:
    """Clear the cache and re-read. For tests and dev. Returns count loaded."""
    _load_filesystem.cache_clear()
    return len(_load_filesystem())
