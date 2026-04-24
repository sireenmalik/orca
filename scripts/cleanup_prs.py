#!/usr/bin/env python3
"""
cleanup_prs.py — demo PR hygiene tool for sireenmalik/orca.

One-off utility for pruning test PRs before / after rehearsals. Never
merges anything — only closes. Uses only the stdlib so the script runs
on the droplet without touching pip.

USAGE
    python3 scripts/cleanup_prs.py
        List every open PR with a KEEP/CLOSE suggestion.

    python3 scripts/cleanup_prs.py --close <N>
        Close PR #N (state=closed, not merged). Errors if N doesn't
        exist or is already closed.

    python3 scripts/cleanup_prs.py --close-suggested
        Close every PR the listing marked CLOSE. Confirms once before
        touching anything.

    python3 scripts/cleanup_prs.py --close-all-by-prefix v2/cfg/
        Close every open PR whose branch starts with the given prefix.
        Confirms once. Useful for "close everything from this rehearsal".

REQUIREMENTS
    GITHUB_TOKEN env var with repo:write on sireenmalik/orca.
    Source it from /opt/orca-v2/.env before running:
        set -a && . /opt/orca-v2/.env && set +a
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


OWNER = "sireenmalik"
REPO  = "orca"
API   = f"https://api.github.com/repos/{OWNER}/{REPO}"

# Title substrings (case-insensitive) that mark a PR as closeable.
CLOSE_TITLE_SUBSTRINGS = ("smoke test", "test proposal")
# Branch prefix that marks a PR as closeable.
CLOSE_BRANCH_PREFIXES  = ("v2/cfg/smoke-",)


def _require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "error: GITHUB_TOKEN is not set.\n"
            "source the droplet env first:\n"
            "    set -a && . /opt/orca-v2/.env && set +a",
            file=sys.stderr,
        )
        sys.exit(2)
    return token


def _call(method: str, path: str, token: str, data=None):
    url = API + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json",
            "User-Agent":    "orca-cleanup-prs",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode() or "{}"
            return json.loads(raw) if raw else {}, r.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode() or "{}"), e.code
        except Exception:
            return {"message": "http error"}, e.code


def _list_open_prs(token: str) -> list:
    """Fetch all open PRs (paginated, 100/page)."""
    prs = []
    page = 1
    while True:
        data, status = _call("GET", f"/pulls?state=open&per_page=100&page={page}", token)
        if status != 200 or not isinstance(data, list):
            print(f"error: /pulls returned {status}: {data}", file=sys.stderr)
            sys.exit(3)
        if not data:
            break
        prs.extend(data)
        if len(data) < 100:
            break
        page += 1
    return prs


def _suggestion(pr: dict) -> str:
    title = (pr.get("title") or "").lower()
    branch = (pr.get("head") or {}).get("ref", "") or ""
    if any(s in title for s in CLOSE_TITLE_SUBSTRINGS):
        return "CLOSE"
    if any(branch.startswith(p) for p in CLOSE_BRANCH_PREFIXES):
        return "CLOSE"
    return "KEEP"


def _age_hours(created_at: str) -> float:
    """Hours between created_at (ISO 8601 Z) and now."""
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
        dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 3600.0
    except Exception:
        return 0.0


def _fmt_created(created_at: str) -> str:
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return created_at or "—"


def cmd_list(token: str) -> list:
    prs = _list_open_prs(token)
    if not prs:
        print("no open PRs on sireenmalik/orca")
        return []

    rows = []
    for pr in prs:
        num    = pr.get("number")
        title  = (pr.get("title") or "").replace("\n", " ")
        branch = (pr.get("head") or {}).get("ref", "") or ""
        created = pr.get("created_at") or ""
        rows.append({
            "num":        num,
            "title":      title[:80] + ("…" if len(title) > 80 else ""),
            "branch":     branch[:48] + ("…" if len(branch) > 48 else ""),
            "created":    _fmt_created(created),
            "age_hours":  _age_hours(created),
            "suggestion": _suggestion(pr),
        })
    rows.sort(key=lambda r: r["num"])

    # Print table
    header = f"{'#PR':>5}  {'AGE':>6}  {'ACTION':<6}  {'CREATED':<21}  {'BRANCH':<50}  TITLE"
    print(header)
    print("-" * min(len(header), 160))
    for r in rows:
        age = f"{r['age_hours']:.1f}h" if r["age_hours"] < 48 else f"{r['age_hours']/24:.1f}d"
        print(f"{r['num']:>5}  {age:>6}  {r['suggestion']:<6}  {r['created']:<21}  {r['branch']:<50}  {r['title']}")

    keep  = sum(1 for r in rows if r["suggestion"] == "KEEP")
    close = sum(1 for r in rows if r["suggestion"] == "CLOSE")
    print()
    print(f"{len(rows)} PRs open · {keep} suggested KEEP · {close} suggested CLOSE")
    return rows


def _close_pr(num: int, token: str) -> bool:
    data, status = _call("PATCH", f"/pulls/{num}", token, {"state": "closed"})
    if status == 200:
        print(f"#{num} closed (not merged)")
        return True
    if status == 404:
        print(f"#{num} not found", file=sys.stderr)
        return False
    print(f"#{num} close failed ({status}): {data}", file=sys.stderr)
    return False


def cmd_close_one(num: int, token: str) -> int:
    data, status = _call("GET", f"/pulls/{num}", token)
    if status != 200:
        print(f"error: PR #{num} not found ({status}): {data}", file=sys.stderr)
        return 1
    if data.get("state") == "closed":
        print(f"#{num} is already closed", file=sys.stderr)
        return 1
    if data.get("merged"):
        print(f"#{num} is already merged — not touching it", file=sys.stderr)
        return 1
    return 0 if _close_pr(num, token) else 1


def _confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes")


def cmd_close_suggested(token: str) -> int:
    rows = cmd_list(token)
    targets = [r for r in rows if r["suggestion"] == "CLOSE"]
    if not targets:
        print("\nnothing to close — no PRs were flagged CLOSE.")
        return 0
    print(f"\nabout to close {len(targets)} PR(s):")
    for r in targets:
        print(f"  #{r['num']}  {r['branch']}  {r['title']}")
    if not _confirm(f"\nClose {len(targets)} PRs? [y/N] "):
        print("aborted — no PRs were touched.")
        return 0
    print()
    closed = sum(1 for r in targets if _close_pr(r["num"], token))
    print(f"\ndone — closed {closed}/{len(targets)}.")
    return 0 if closed == len(targets) else 1


def cmd_close_by_prefix(prefix: str, token: str) -> int:
    prs = _list_open_prs(token)
    targets = [
        pr for pr in prs
        if ((pr.get("head") or {}).get("ref", "") or "").startswith(prefix)
    ]
    if not targets:
        print(f"nothing to close — no open PR has branch starting with {prefix!r}.")
        return 0
    print(f"about to close {len(targets)} PR(s) on branches matching {prefix!r}:")
    for pr in targets:
        branch = (pr.get("head") or {}).get("ref", "")
        print(f"  #{pr['number']}  {branch}  {(pr.get('title') or '')[:80]}")
    if not _confirm(f"\nClose {len(targets)} PRs? [y/N] "):
        print("aborted — no PRs were touched.")
        return 0
    print()
    closed = sum(1 for pr in targets if _close_pr(pr["number"], token))
    print(f"\ndone — closed {closed}/{len(targets)}.")
    return 0 if closed == len(targets) else 1


def main():
    parser = argparse.ArgumentParser(
        description="Demo PR hygiene for sireenmalik/orca. Never merges — only closes.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--close", type=int, metavar="N",
                       help="close a single PR by number")
    group.add_argument("--close-suggested", action="store_true",
                       help="close every PR the listing flagged CLOSE (confirms once)")
    group.add_argument("--close-all-by-prefix", metavar="PREFIX",
                       help="close every open PR whose branch starts with PREFIX (confirms once)")
    args = parser.parse_args()

    token = _require_token()

    if args.close is not None:
        sys.exit(cmd_close_one(args.close, token))
    if args.close_suggested:
        sys.exit(cmd_close_suggested(token))
    if args.close_all_by_prefix:
        sys.exit(cmd_close_by_prefix(args.close_all_by_prefix, token))

    cmd_list(token)


if __name__ == "__main__":
    main()
