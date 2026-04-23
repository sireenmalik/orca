# ORCA Session State
**Read this first. Every session. Before touching any code.**

---

## Current State (last updated: 2026-04-23)

### Live URL
**http://206.189.209.48** — v33 (may change on next deploy — check DO API)

### Find current droplet
```bash
curl -s "https://api.digitalocean.com/v2/droplets?tag_name=orca" \
  -H "Authorization: Bearer dop_v1_60651458efb36ecb98f382f8f8daa19a086bf4f8444f93ad98d84541258b174d" | \
  python3 -c "
import json,sys
for d in json.load(sys.stdin)['droplets']:
    pub=[n for n in d['networks']['v4'] if n['type']=='public']
    print(d['id'], pub[0]['ip_address'] if pub else 'no-ip', d['status'])
"
```

---

## What Was Last Built (v33)

### Three complete use cases:
1. **Network Operations** — fault inject → CSPF reroute → config proposal → Approve & Push → GitHub PR + episode
2. **Security Breach** — rogue config inject → immediate Security tab alert → ORCA detects drift → evidence archived to Git → human-gated revert proposal
3. **Churn Forecast** — live SLA risk scores per customer LSP, counterfactual panel, annotated churn chart

### Last 5 significant changes:
1. `raise_security_alert` now sends structured security email with evidence PR link immediately
2. `EmailCard` component — expandable cards with full scrollable body and auto-extracted GitHub link buttons (PR #N, 📚 Episode, 🔐 Evidence)
3. Email dedup fixed — PR/episode/security emails always get through regardless of timing
4. Security tab listens for both `security_alert` AND `security_alarm` event types
5. `ORCA-SPEC.md`, `ORCA-DEPLOY.skill.md`, `ORCA-FRONTEND.skill.md`, `ORCA-AGENT.skill.md` committed to `docs/`

---

## Known Issues / Not Yet Done

- [ ] Nokia SR-OS adapter (gNMI/NETCONF) — not built, ContainerlabAdapter is the only adapter
- [ ] Microsoft Teams integration — not built
- [ ] Security tab "Reset Demo" button clears alerts but does not clear config proposals created by security flow — do manually via `DELETE /api/config-proposals`
- [ ] Churn counterfactual panel only appears after `agent_status.status === "complete"` event — requires running Analyze to completion
- [ ] Email outbox doesn't persist across container restarts (in-memory queue)

---

## How to Start a Session

### Step 1 — Fetch live files (always do this, never use memory)
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
    with open(f'/home/claude/{path.split("/")[-1]}', 'w') as f:
        f.write(content)
    print(f"✅ {path} ({len(content)//1024}KB)")

fetch("api/main.py")
fetch("agent/te_agent.py")
fetch("agent/adapter.py")
fetch("agent/notifications.py")
fetch("dashboard/src/App.jsx")
```

### Step 2 — Read the relevant skill file
- Changing backend logic → read `docs/ORCA-AGENT.skill.md`
- Changing frontend → read `docs/ORCA-FRONTEND.skill.md`
- Deploying → read `docs/ORCA-DEPLOY.skill.md`
- Architecture questions → read `docs/ORCA-SPEC.md`

### Step 3 — Make changes to local files, push via GitHub API, patch server
```bash
# Push
python3 push_script.py   # see ORCA-DEPLOY.skill.md for pattern

# Patch (user runs in DO console)
cd /opt/orca && git pull origin main && docker-compose restart && echo DONE
```

---

## Demo Tabs (open before presenting)

| Tab | URL |
|-----|-----|
| Dashboard | `http://{CURRENT_IP}` |
| GitHub PRs | `https://github.com/sireenmalik/orca/pulls` |
| Config files | `https://github.com/sireenmalik/orca/tree/main/config_mgmt` |
| Episodes | `https://github.com/sireenmalik/orca/tree/main/skills/past/episodes` |
| Security evidence | `https://github.com/sireenmalik/orca/tree/main/security/incidents` |

---

## Demo Script (12 minutes)

### Use Case 1 — Network Operations (5 min)
1. Show healthy topology — all green, utilization live
2. Select R1-R4 → **Inject Fault** → topology turns red
3. Click **Analyze** — walk agent log: OBSERVE → THINK (CSPF) → TOOL (reroute) → RESULT → NOTIFY → TAC → PROPOSE
4. Config Proposals badge → click proposal → modal: left sidebar 6 checks, center diff (red/green), right proposed config, device tabs
5. **Approve & Push** → git commands stream → NETCONF push → PR opened
6. Switch to GitHub → show PR body: incident table, missions ✅✅, validation table with detail, per-router diff
7. Switch to Episodes → show YAML: trigger, missions, validation, config_change block with PR cross-ref

### Use Case 2 — Security (3 min)
1. Click **🔓 Inject Rogue Config** → Security tab immediately shows CRITICAL LIVE
2. Click **Security** tab → show alert: node R1, source IP 10.0.3.44, NETCONF direct push
3. Threat intel block: CISA AA24-038A (Salt Typhoon) reference
4. Click **Analyze** → log: detect_config_drift → raise_security_alert → evidence archived
5. Config Proposals → red SECURITY badge → modal shows revert diff
6. GitHub → evidence PR (auto, archival) in `security/incidents/`
7. **Approve & Push** → revert pushed via NETCONF
8. Email Outbox → expand security email card → evidence PR link + revert confirmation
9. Click **🔄 Reset Demo** when done

### Use Case 3 — Churn (2 min)
1. Click **Churn Forecast** tab
2. Live SLA Risk panel: Customer-A healthy (risk 34, churn 5%) because ORCA responded in 47s
3. Counterfactual panel: without ORCA → risk 71, churn 78%, $2.4M ARR at risk
4. Chart: two incidents annotated, red dashed "without ORCA" line diverges +1.35% by Aug
5. *"ORCA didn't just fix the network. It protected the revenue."*

### Close (30s)
> *"Three capabilities. One platform. Network ops, security, customer experience. Nokia SR-OS adapter via gNMI/NETCONF is next. What would it take to run this on your network?"*

---

## Updating This File

Update `docs/ORCA-SESSION.md` at the end of every session with:
- New current IP
- Last 5 changes made
- Any new known issues
- Anything that broke and was fixed

This is the most important file in the repo.
