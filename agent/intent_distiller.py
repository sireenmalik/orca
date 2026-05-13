"""
ORCA Intent Distiller — turns one resolved episode into one candidate
policy intent (L5 closed-loop learning).

Reads an episode YAML (the deterministic shape v2.2.0-episode-shape
emits, with the Distiller-targeted RESOLUTION block), calls Nemotron
at high reasoning_effort with the prompt at prompts/intent_distiller.txt,
parses the YAML reply into a policy-intent dict, and writes it to
GitHub at intents/policy/pending/<intent_id>.yaml on `main`.

Operator-side review then either ratifies (PR moves pending → policy)
or rejects (PR moves pending → archive) — those endpoints live in
api/main.py and are wired in a separate step.

Failure modes are deliberately non-propagating: the save flow is the
critical path, the Distiller is non-critical learning. A bad NIM call,
malformed YAML reply, or GitHub push failure must NOT break the demo —
each is logged and swallowed. See distill_episode_safe() for the
guaranteed-no-raise entry point used from te_agent / scenarios.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from openai import AsyncOpenAI as _AsyncOpenAI  # type: ignore
except ImportError:
    _AsyncOpenAI = None  # type: ignore

try:
    import yaml as _yaml  # type: ignore
except ImportError:
    _yaml = None  # type: ignore


PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "intent_distiller.txt"


def _new_intent_id() -> str:
    """pol-2026-<6 hex>"""
    year = datetime.utcnow().strftime("%Y")
    return f"pol-{year}-{uuid.uuid4().hex[:6]}"


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_prompt(episode_yaml: str, intent_id: str, timestamp: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return (template
            .replace("{episode_yaml}", episode_yaml)
            .replace("{intent_id}",   intent_id)
            .replace("{timestamp}",   timestamp))


async def _call_nemotron(prompt: str) -> str:
    """Call NIM with reasoning_effort=high, return raw text. Raises on failure."""
    if _AsyncOpenAI is None:
        raise RuntimeError("openai package not installed — cannot call NIM")
    client = _AsyncOpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key=os.getenv("NVIDIA_API_KEY"),
    )
    resp = await client.chat.completions.create(
        model=os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10000,
        temperature=0.2,
        extra_body={
            "reasoning_effort":  "high",
            "reasoning_budget":  8000,
        },
    )
    return (resp.choices[0].message.content or "").strip()


def _strip_code_fences(text: str) -> str:
    """Some models wrap YAML in ```yaml fences despite the prompt rule."""
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        t = t[first_nl + 1:] if first_nl != -1 else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _push_pending_to_github(intent_id: str, intent_yaml: str) -> Optional[str]:
    """PUT the pending intent to intents/policy/pending/<id>.yaml on main.
    Returns the GitHub html_url or None on failure (failure logged, no raise).
    Mirrors the pattern in te_agent._write_episode."""
    token      = os.getenv("GITHUB_TOKEN", "")
    repo_owner = os.getenv("GITHUB_OWNER", "sireenmalik")
    repo_name  = os.getenv("GITHUB_REPO",  "orca")
    if not token:
        print(f"[distiller] GITHUB_TOKEN not set — pending intent {intent_id} "
              f"not pushed", flush=True)
        return None
    path    = f"intents/policy/pending/{intent_id}.yaml"
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"
    payload = json.dumps({
        "message": f"distiller: propose policy intent {intent_id}",
        "content": base64.b64encode(intent_yaml.encode("utf-8")).decode("ascii"),
        "branch":  "main",
    }).encode("utf-8")
    req = urllib.request.Request(
        api_url, data=payload, method="PUT",
        headers={
            "Authorization": f"token {token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("content", {}).get("html_url", "")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")[:200]
        except Exception:
            pass
        print(f"[distiller] push failed {e.code}: {body}", flush=True)
        return None
    except Exception as e:
        print(f"[distiller] push exception: {type(e).__name__}: {e}", flush=True)
        return None


# ─── In-memory pending list ──────────────────────────────────────────────────
# Pending intents also held in memory so the dashboard can read them via
# /api/policy/pending without paying a GitHub round-trip per request. The
# GitHub copy at intents/policy/pending/<id>.yaml is the durable record.

_pending_intents: list = []


def get_pending_intents() -> list:
    return list(_pending_intents)


def clear_pending_intents() -> None:
    _pending_intents.clear()


def pop_pending_intent(intent_id: str) -> Optional[dict]:
    """Remove and return the named pending intent, or None."""
    for i, p in enumerate(_pending_intents):
        if p.get("intent_id") == intent_id:
            return _pending_intents.pop(i)
    return None


async def distill_episode(episode_yaml: str) -> Optional[dict]:
    """Read one episode YAML, propose one candidate policy intent.

    Returns the parsed intent dict on success, or None when:
      - the model said no_high_confidence_pattern_found
      - YAML parse failed
      - the NIM call raised

    Side effects on success:
      - the intent dict is appended to _pending_intents
      - the YAML is pushed to GitHub at intents/policy/pending/<id>.yaml
      - the intent dict carries 'github_url' (or "" if push failed)
    """
    if _yaml is None:
        print("[distiller] pyyaml not installed — cannot parse reply", flush=True)
        return None
    intent_id = _new_intent_id()
    timestamp = _now_iso()
    prompt    = _load_prompt(episode_yaml, intent_id, timestamp)

    try:
        raw = await _call_nemotron(prompt)
    except Exception as e:
        print(f"[distiller] NIM call failed: {type(e).__name__}: {e}",
              flush=True)
        return None

    body = _strip_code_fences(raw)
    if body.startswith("no_high_confidence_pattern_found"):
        print(f"[distiller] {intent_id}: no_high_confidence_pattern_found",
              flush=True)
        return None

    try:
        parsed = _yaml.safe_load(body)
    except Exception as e:
        print(f"[distiller] YAML parse failed for {intent_id}: {e}\n"
              f"raw head: {body[:300]}", flush=True)
        return None
    if not isinstance(parsed, dict) or "intent_id" not in parsed:
        print(f"[distiller] {intent_id}: reply not a policy intent dict\n"
              f"raw head: {body[:300]}", flush=True)
        return None

    # Force-stamp the canonical id / timestamp in case the model echoed
    # the placeholder text or invented a different id.
    parsed["intent_id"]   = intent_id
    parsed["proposed_at"] = timestamp
    parsed.setdefault("proposed_by", "orca-distiller")

    # Re-dump to canonical YAML for the durable record.
    canonical_yaml = _yaml.safe_dump(parsed, sort_keys=False,
                                     default_flow_style=False).strip() + "\n"
    gh_url = _push_pending_to_github(intent_id, canonical_yaml)
    parsed["github_url"] = gh_url or ""
    _pending_intents.append(parsed)
    print(f"[distiller] proposed {intent_id} → action={parsed.get('action', {}).get('type','?')} "
          f"confidence={parsed.get('confidence','?')} gh={gh_url or 'no-push'}",
          flush=True)
    return parsed


async def distill_episode_safe(episode_yaml: str) -> Optional[dict]:
    """Top-level entry point for save-flow callers. Never raises.
    Use this from te_agent / scenarios where the save path must not break."""
    try:
        return await distill_episode(episode_yaml)
    except Exception as e:
        print(f"[distiller] unexpected error (swallowed): "
              f"{type(e).__name__}: {e}", flush=True)
        return None


# ─── CLI ─────────────────────────────────────────────────────────────────────
# Usage: python -m agent.intent_distiller <episode_path_or_url>
#   - path: read the file
#   - url:  fetch via urllib (with GITHUB_TOKEN if set)

def _load_episode_source(src: str) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        req = urllib.request.Request(src)
        token = os.getenv("GITHUB_TOKEN", "")
        if token and "api.github.com" in src:
            req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github.raw")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    return Path(src).read_text(encoding="utf-8")


def _main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m agent.intent_distiller <episode_path_or_url>",
              file=sys.stderr)
        return 2
    src = sys.argv[1]
    episode_yaml = _load_episode_source(src)
    result = asyncio.run(distill_episode(episode_yaml))
    if result is None:
        print("no intent proposed", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
