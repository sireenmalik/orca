# ORCA Deployment Skill
**Read this before any deploy, file edit, or infrastructure change.**

---

## The Golden Rule

**NEVER destroy a droplet to deploy code changes.**
**NEVER run `docker build --no-cache` unless a Python dependency changed.**
**NEVER rebuild the frontend unless `package.json` changed.**

---

## Standard Patch (15 seconds)

This is the ONLY deploy method for code changes:

```bash
cd /opt/orca && git pull origin main && docker-compose restart && echo DONE
```

The container serves a pre-built `dashboard/dist/` — git pull picks up new Python and JSX files, restart applies them. No npm, no rebuild.

**When to use:** Any change to `api/main.py`, `agent/te_agent.py`, `agent/adapter.py`, `agent/notifications.py`, `dashboard/src/App.jsx`, or any other source file.

---

## When a Full Rebuild IS Required

Only these cases require `docker-compose down && docker build`:

1. `Dockerfile.api` changed
2. `requirements.txt` changed (new Python package)
3. `dashboard/package.json` changed (new npm package)
4. Container is in restart loop due to import error

```bash
cd /opt/orca && docker-compose down && docker build -f Dockerfile.api -t orca_api:latest . 2>&1 | tail -10 && docker-compose --env-file .env up -d && echo DONE
```

**Takes ~3-5 minutes** (uses layer cache). Check `docker logs orca_api_1 --tail 20` after.

---

## Pushing Files to GitHub (from Claude sandbox)

Claude's sandbox cannot SSH. All file updates go via GitHub API:

```python
import urllib.request, json, base64

token = "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"
headers = {"Authorization": f"token {token}", "Content-Type": "application/json",
           "Accept": "application/vnd.github.v3+json"}

def push(path, local_path, message):
    req = urllib.request.Request(
        f"https://api.github.com/repos/sireenmalik/orca/contents/{path}", headers=headers)
    with urllib.request.urlopen(req) as r:
        sha = json.loads(r.read())["sha"]
    with open(local_path, 'r') as f:
        content = f.read()
    data = json.dumps({
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "sha": sha
    }).encode()
    req2 = urllib.request.Request(
        f"https://api.github.com/repos/sireenmalik/orca/contents/{path}",
        data=data, method="PUT", headers=headers)
    with urllib.request.urlopen(req2) as r:
        print(f"✅ {path} → {json.loads(r.read())['commit']['sha'][:8]}")
```

**Always fetch the current file first** to get its SHA before pushing. Pushing without SHA fails.

---

## Triggering a Patch After Push

After pushing to GitHub, the patch command must be run on the server. Options:

1. **User runs in DO console** — fastest, tell them:
   ```
   cd /opt/orca && git pull origin main && docker-compose restart && echo DONE
   ```

2. **Claude cannot SSH** — no SSH client in sandbox. Do not attempt.

3. **DO API cannot exec** — the DigitalOcean API has no shell exec endpoint.

4. **Full redeploy** — only if patch cannot work (e.g. restart loop). See below.

---

## Spinning a New Droplet

Use this pattern when a full rebuild is needed or the droplet is broken:

```python
import gzip, base64, yaml, urllib.request, json, time

TOKEN = "dop_v1_60651458efb36ecb98f382f8f8daa19a086bf4f8444f93ad98d84541258b174d"
GH_TOKEN = "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"
ANTHROPIC_KEY = "sk-ant-api03-..."
SG_KEY = "SG.l2SR..."

script = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git curl docker.io docker-compose python3-pip nodejs npm 2>&1|tail -3
systemctl enable docker && systemctl start docker
cd /opt && git clone https://{GH_TOKEN}@github.com/sireenmalik/orca.git orca 2>&1|tail -3
cd /opt/orca
cat>/opt/orca/.env<<'ENVEOF'
ANTHROPIC_API_KEY={ANTHROPIC_KEY}
DB_PATH=/data/orca.db
NETWORK_ADAPTER=containerlab
AGENT_POLL_INTERVAL=15
OPS_EMAIL=sireenmalik@gmail.com
SENDGRID_API_KEY={SG_KEY}
GITHUB_TOKEN={GH_TOKEN}
GITHUB_OWNER=sireenmalik
GITHUB_REPO=orca
ENVEOF
mkdir -p /opt/orca/data
pip3 install anthropic fastapi uvicorn websockets PyGithub aiohttp pyyaml --break-system-packages -q 2>&1|tail -3
docker build -f Dockerfile.api -t orca_api:latest . 2>&1|tail -5
docker-compose --env-file .env up -d
sleep 5 && curl -s localhost:8000/api/health
echo "ORCA vN LIVE $(date)"|tee /var/log/orca.log"""

compressed = gzip.compress(script.encode())
b64 = base64.b64encode(compressed).decode()
ci = {'write_files': [{'path': '/opt/setup.b64', 'content': b64, 'permissions': '0644'}],
      'runcmd': ['base64 -d /opt/setup.b64|gunzip|bash 2>&1|tee /var/log/orca-init.log']}
ci_str = '#cloud-config\n' + yaml.dump(ci, default_flow_style=False)

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
payload = json.dumps({
    "name": "orca-demo", "region": "sfo2", "size": "s-4vcpu-8gb",
    "image": "ubuntu-24-04-x64", "ssh_keys": [54443503, 53273622],
    "user_data": ci_str, "tags": ["orca", "demo"]
}).encode()
```

**Always** assign to firewall `5a6f549a-8561-4a7e-809a-e8bd6ffeac18` after creation.

**Takes ~10 minutes** to be ready after droplet goes active.

**DO API returns 503 occasionally** — retry up to 5 times with 20s sleep.

---

## Finding the Current Droplet

```bash
curl -s "https://api.digitalocean.com/v2/droplets?tag_name=orca" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import json,sys
drops=json.load(sys.stdin).get('droplets',[])
for d in drops:
    pub=[n for n in d['networks']['v4'] if n['type']=='public']
    print(d['id'], pub[0]['ip_address'] if pub else 'no-ip', d['status'])
"
```

---

## Verifying Deployment

Claude's sandbox cannot reach DO IPs directly (403 from proxy). Cannot verify from here.

**Tell the user to check:**
```bash
docker ps
docker logs orca_api_1 --tail 20
curl -s localhost:8000/api/health
```

Or check browser at `http://{IP}`.

**Never report deployment as healthy without direct evidence.**

---

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Container restart loop | SyntaxError in Python (often f-string with backslash in Python 3.11) | Fix code, push, rebuild |
| Site unreachable after 20min | Build still running (npm takes 8-15min) | Wait, check `tail -f /var/log/orca-init.log` |
| `docker-compose restart` shows no change | Old Docker image cached | Run full `docker build` command |
| DO API 503 | Transient DO outage | Retry with 15-20s sleep |
| `git pull` says "already up to date" but changes not live | Docker not restarted | Run `docker-compose restart` |
| f-string SyntaxError on Python 3.11 | Backslash inside `f"...{...}"` | Extract variable before f-string |

---

## File Locations on Server

```
/opt/orca/                  project root
/opt/orca/.env              environment variables
/opt/orca/api/main.py       FastAPI backend
/opt/orca/agent/            agent code
/opt/orca/dashboard/src/    React source
/opt/orca/dashboard/dist/   built frontend (served by container)
/opt/orca/data/             SQLite DB
/var/log/orca-init.log      cloud-init build log
/var/log/orca.log           app start marker
```

---

## SSH Direct Access (use this — stop rebuilding droplets)

### Setup at start of every session (30 seconds)

```bash
# Step 1 — install SSH and restore deploy key
curl -s https://raw.githubusercontent.com/sireenmalik/orca/main/scripts/setup_ssh.sh \
  -H "Authorization: token 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" | bash

# OR fetch via GitHub API and run locally:
curl -s -H "Authorization: token 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" \
  "https://api.github.com/repos/sireenmalik/orca/contents/scripts/setup_ssh.sh" | \
  python3 -c "import json,sys,base64; print(base64.b64decode(json.load(sys.stdin)['content']).decode())" \
  > /tmp/setup_ssh.sh && bash /tmp/setup_ssh.sh
```

This installs openssh-client, writes the deploy key to `~/.ssh/orca_deploy_key`, and prints `ORCA_IP`.

### SSH key details

| Item | Value |
|------|-------|
| Key name | `orca-ci-key` |
| DO key ID | `55825147` |
| Fingerprint | `87:cc:eb:69:f5:a1:a6:95:2b:fe:44:d0:58:8f:05:3c` |
| Stored in repo | `scripts/setup_ssh.sh` (base64 embedded) |

**All new droplets must include this key ID**: `[54443503, 53273622, 55825147]`

### Common SSH commands

```bash
# Patch — the only deploy method for code changes (15 seconds)
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP \
  'cd /opt/orca && git pull origin main && docker-compose restart && echo DONE'

# Check container status
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP \
  'docker ps && docker logs orca_api_1 --tail 20'

# Check build log (during cloud-init)
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP \
  'tail -30 /var/log/orca-init.log'

# Full rebuild (only when Dockerfile/package.json changed)
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP \
  'cd /opt/orca && docker-compose down && docker build -f Dockerfile.api -t orca_api:latest . 2>&1 | tail -5 && docker-compose --env-file .env up -d && echo DONE'

# Check health
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP \
  'curl -s localhost:8000/api/health'

# Interactive shell
ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP
```

### Helper function — set ORCA_IP automatically

```bash
ORCA_IP=$(curl -s "https://api.digitalocean.com/v2/droplets?tag_name=orca" \
  -H "Authorization: Bearer dop_v1_60651458efb36ecb98f382f8f8daa19a086bf4f8444f93ad98d84541258b174d" | \
  python3 -c "
import json,sys
drops=json.load(sys.stdin).get('droplets',[])
pub=[n for n in drops[0]['networks']['v4'] if n['type']=='public'] if drops else []
print(pub[0]['ip_address'] if pub else 'NOT_FOUND')
")
echo "ORCA at: $ORCA_IP"
```

### Why SSH matters

Without SSH, every code fix requires spinning a new droplet (10 min). With SSH, a patch takes 15 seconds. The sandbox has no SSH client by default — the setup script installs it. Do this at the start of every session before any deployment work.
