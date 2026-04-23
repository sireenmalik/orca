# ORCA — Autonomous Network Operations & Response Agent

---

## ⚠️ FOR ANY AI ASSISTANT WORKING ON THIS REPO

**STOP. Read this before writing a single line of code.**

This project has detailed skill and spec files that capture every architectural decision, data structure, key name, deployment pattern, and known bug fix. Ignoring them will reproduce bugs that have already been fixed and break things that already work.

### Mandatory reading order — every session, no exceptions:

```
1. docs/ORCA-SESSION.md       ← Start here. Current IP, last changes, known issues, how to fetch files
2. docs/ORCA-SPEC.md          ← Architecture, API endpoints, data structures, use cases
3. docs/ORCA-DEPLOY.skill.md  ← Deployment rules (patch vs rebuild, cloud-init pattern)
4. docs/ORCA-FRONTEND.skill.md ← Dashboard components, event types, Python 3.11 compat
5. docs/ORCA-AGENT.skill.md   ← Tools, approval flow, system prompt, stores
```


### Step 0 (before anything else) — Set up SSH

**Do this at the start of every session. It gives you direct server access in 30 seconds.**

```bash
# Fetch and run the SSH setup script
curl -s -H "Authorization: token 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" \
  "https://api.github.com/repos/sireenmalik/orca/contents/scripts/setup_ssh.sh" | \
  python3 -c "import json,sys,base64; print(base64.b64decode(json.load(sys.stdin)['content']).decode())" \
  > /tmp/setup_ssh.sh && bash /tmp/setup_ssh.sh
```

This installs `openssh-client`, writes the deploy key to `~/.ssh/orca_deploy_key`, and prints `ORCA_IP`.

Then patch in 15 seconds instead of rebuilding in 10 minutes:
```bash
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP \
  'cd /opt/orca && git pull origin main && docker-compose restart && echo DONE'
```

Full SSH reference: `docs/ORCA-DEPLOY.skill.md` → **SSH Direct Access** section.

### Then fetch the live source files before touching them:

```python
import urllib.request, json, base64

token = "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"
headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

def fetch(path):
    req = urllib.request.Request(
        f"https://api.github.com/repos/sireenmalik/orca/contents/{path}", headers=headers)
    with urllib.request.urlopen(req) as r:
        d = json.loads(r.read())
    content = base64.b64decode(d['content']).decode()
    local = f'/home/claude/{path.split("/")[-1]}'
    with open(local, 'w') as f: f.write(content)
    print(f"✅ {path} ({len(content)//1024}KB sha:{d['sha'][:8]})")

fetch("api/main.py")
fetch("agent/te_agent.py")
fetch("agent/adapter.py")
fetch("agent/notifications.py")
fetch("dashboard/src/App.jsx")
```

**Never edit from memory. Never assume file content. Always fetch first.**

### Critical rules that burn sessions if ignored:

| Rule | Why |
|------|-----|
| Patch = `git pull && docker-compose restart` | Never destroy droplet for code changes |
| Both `/approved` AND `/approve` routes must exist | Frontend posts to `/approved`, missing it silently does nothing |
| Agent sends `device` key in changes, not `node` | Wrong key = "Router" tab, "metric old/new" placeholders |
| Python 3.11: no backslash inside f-string expressions | SyntaxError crash, container restart loop |
| `validation_checks` (bool) + `validation_detail` (string) are separate keys | Merging them breaks the modal and the PR body |
| `send_email()` already queues — don't call a separate `queue_email()` | Doesn't exist, causes ImportError |
| DO API returns 503 occasionally | Retry up to 5 times with 20s sleep |

### After every session — update `docs/ORCA-SESSION.md`:
- New droplet IP
- Last 5 changes made
- Any new known issues

---

## What ORCA Is

AI-native network operations platform using Claude Sonnet as its reasoning engine. Three live use cases:

1. **Network Operations** — autonomous fault detection, CSPF rerouting, config proposal with human approval, GitHub PR + episode audit trail
2. **Security** — unauthorized config change detection, evidence archival to Git, human-gated revert, CISA AA24-038A threat intel mapping
3. **Churn Forecast** — live SLA risk scoring per customer LSP, logistic churn model, counterfactual revenue protection

### The Two Missions
- **Mission 1** — All link utilization below 90% (hard constraint)
- **Mission 2** — Minimize maximum utilization across all links (objective)

### Architecture
```
Frontend    React + D3 + Vite          dashboard/src/App.jsx
Backend     FastAPI + WebSocket         api/main.py
Agent       Claude Sonnet              agent/te_agent.py
Adapter     ContainerlabAdapter        agent/adapter.py
Notify      SendGrid + mailto queue    agent/notifications.py
Network     Simulated 6-node ring      ContainerlabAdapter
```

Full architecture, API endpoints, data structures, and use case flows: **`docs/ORCA-SPEC.md`**

---

## Quick Start

```bash
git clone https://github.com/sireenmalik/orca.git
cd orca
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY, GITHUB_TOKEN, OPS_EMAIL

docker build -f Dockerfile.api -t orca_api:latest .
docker-compose --env-file .env up -d

open http://localhost
```

---

## Docs

| File | Purpose |
|------|---------|
| `docs/ORCA-SESSION.md` | **Start here** — current state, live IP, demo script |
| `docs/ORCA-SPEC.md` | Master spec — architecture, API, data structures |
| `docs/ORCA-DEPLOY.skill.md` | Deployment rules and patterns |
| `docs/ORCA-FRONTEND.skill.md` | Dashboard development rules |
| `docs/ORCA-AGENT.skill.md` | Agent tools, flows, system prompt |

---

## Vendor Support

| Vendor | Status |
|--------|--------|
| Containerlab (simulated) | ✅ Live |
| Nokia SR-OS (gNMI/NETCONF) | 🔲 Next |
| Cisco IOS-XR | 🔲 Planned |
| Juniper Junos | 🔲 Planned |

---

## Built With

Claude Sonnet 4 · FastAPI · React · D3 · DigitalOcean · GitHub
