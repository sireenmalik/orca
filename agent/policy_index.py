"""
ORCA Policy Index — in-memory match index of ratified policy intents.

Loads intents from intents/policy/*.yaml on the live `main` branch via
the GitHub Contents API (the same durable store the Distiller writes
to). Holds parsed intents in memory and exposes match(fault_signature)
for runtime lookup. Used by:

  - GET /api/policy/ratified  (lists ratified intents)
  - match_policy_intent tool  (te_agent tool registration)

Refresh strategy: polled at startup + on-demand (POST /api/policy/reload
or a future watchdog) — simple polling is plenty for the demo.

Match logic: each `intent.match` is a flat dict of {signal_name:
threshold-expression}. Threshold expressions: numeric ops (>, >=, <,
<=, =, ==), equality (== "value" or bare string), or list membership.
A fault matches an intent if EVERY signal in intent.match is satisfied
by the fault_signature dict supplied at call time.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

try:
    import yaml as _yaml  # type: ignore
except ImportError:
    _yaml = None  # type: ignore


# Module-level cache. Populated by reload(); read by match() and the
# GET /api/policy/ratified endpoint.
_intents: list = []


def get_ratified_intents() -> list:
    return list(_intents)


# ─── GitHub-listing helpers ──────────────────────────────────────────────────

def _gh_list(path: str) -> list:
    """List files at the given repo path on main, via GitHub Contents API.
    Returns the API's list-of-dicts payload (each dict has 'name', 'path',
    'download_url', ...). On any error, returns []."""
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/{path}?ref=main")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        **({"Authorization": f"token {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data if isinstance(data, list) else []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        print(f"[policy-index] gh list {path} failed {e.code}", flush=True)
        return []
    except Exception as e:
        print(f"[policy-index] gh list {path} exception: "
              f"{type(e).__name__}: {e}", flush=True)
        return []


def _gh_fetch_raw(path: str) -> Optional[str]:
    """Fetch the raw contents of a file at path on main. Returns text or None."""
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    url = (f"https://api.github.com/repos/{repo_owner}/{repo_name}"
           f"/contents/{path}?ref=main")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw",
        **({"Authorization": f"token {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"[policy-index] fetch {path} failed: "
              f"{type(e).__name__}: {e}", flush=True)
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

def reload() -> int:
    """Re-scan intents/policy/*.yaml on main, repopulate the cache.
    Returns the count of intents loaded."""
    if _yaml is None:
        print("[policy-index] pyyaml not installed", flush=True)
        return 0
    listing = _gh_list("intents/policy")
    parsed = []
    for entry in listing:
        if entry.get("type") != "file":
            continue
        name = entry.get("name", "")
        if not name.endswith(".yaml"):
            continue
        raw = _gh_fetch_raw(entry["path"])
        if not raw:
            continue
        try:
            doc = _yaml.safe_load(raw)
        except Exception as e:
            print(f"[policy-index] parse {name} failed: {e}", flush=True)
            continue
        if isinstance(doc, dict) and doc.get("intent_id"):
            parsed.append(doc)
    _intents[:] = parsed
    print(f"[policy-index] reloaded {len(_intents)} ratified intent(s)",
          flush=True)
    return len(_intents)


# ─── Match-condition evaluation ──────────────────────────────────────────────

_NUM_OP_RE = re.compile(r"^\s*(>=|<=|==|>|<|=)\s*([-+]?\d+(?:\.\d+)?)\s*$")
_EQ_OP_RE  = re.compile(r"^\s*==\s*(.+?)\s*$")


def _to_num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cond_match(condition: Any, value: Any) -> bool:
    """Does a fault `value` satisfy an intent match `condition`?

    Numeric ops:  ">90", ">=2", "<50", "==13.0"
    Equality:     "==gbr_mismatch"  or  bare "ok"
    List values:  matches if value is IN the list
    Booleans:     direct ==
    """
    # List condition → value-in-list
    if isinstance(condition, list):
        return value in condition

    # Bool / numeric direct equality
    if isinstance(condition, (bool, int, float)):
        return condition == value or _to_num(value) == _to_num(condition)

    if not isinstance(condition, str):
        return condition == value

    cs = condition.strip()

    # Numeric op like ">90", ">=2"
    m = _NUM_OP_RE.match(cs)
    if m:
        op, rhs = m.group(1), float(m.group(2))
        lhs = _to_num(value)
        if lhs is None:
            return False
        return {
            ">":  lhs >  rhs,
            ">=": lhs >= rhs,
            "<":  lhs <  rhs,
            "<=": lhs <= rhs,
            "=":  lhs == rhs,
            "==": lhs == rhs,
        }[op]

    # Explicit equality with non-numeric ("==gbr_mismatch")
    m = _EQ_OP_RE.match(cs)
    if m:
        return str(value).strip() == m.group(1).strip()

    # Bare string — equality
    return str(value).strip() == cs


def _intent_matches(intent: dict, fault_signature: dict) -> bool:
    match_block = intent.get("match") or {}
    if not isinstance(match_block, dict) or not match_block:
        return False
    for signal, condition in match_block.items():
        if signal not in fault_signature:
            return False
        if not _cond_match(condition, fault_signature[signal]):
            return False
    return True


def match(fault_signature: dict, min_confidence: float = 0.75) -> Optional[dict]:
    """Return the highest-confidence ratified intent that matches the
    fault signature and clears `min_confidence`, or None."""
    if not isinstance(fault_signature, dict):
        return None
    candidates = [i for i in _intents
                  if _intent_matches(i, fault_signature)
                  and float(i.get("confidence", 0) or 0) >= min_confidence]
    if not candidates:
        return None
    return max(candidates,
               key=lambda i: float(i.get("confidence", 0) or 0))
