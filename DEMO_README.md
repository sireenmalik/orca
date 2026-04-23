# ORCA Demo Ops — v1 ↔ v2 Switching

This repo hosts two parallel demos:

| Version | Branch | Droplet path | Port | Theme |
|---|---|---|---|---|
| `v1.0.0` | `main` (pinned to tag `v1.0.0`) | `/opt/orca` | 80 | IP/MPLS transport ops — LSP reroute + security + churn |
| `v2.x`   | `demo/5g-ran`                   | `/opt/orca-v2` | 80 | 5G RAN ops — gNBs + UPFs + slice SLA + transport correlation |

Both share port 80, so **only one runs at a time**. Switching is controlled by two shell scripts installed on the droplet host.

---

## Switching

From any droplet SSH session:

```
demo-v1      # stops v2, starts v1, verifies /api/health before returning
demo-v2      # stops v1, starts v2, verifies /api/health before returning
```

Both scripts:
1. `docker-compose down` on the currently-running stack
2. `docker-compose up -d` on the target stack
3. Poll `curl http://localhost/api/health` for up to 20s and echo `✅` only when the response contains `"status":"ok"`

If the health check fails after 20s, the script exits non-zero and tails container logs so you can see what broke.

A warm switch (both images already built) takes **~10–15 seconds**. A cold switch that includes a rebuild can take up to 90s.

---

## Pre-flight checklist (morning of any demo)

Run these in order ~30 minutes before the briefing. Any failure — **stop and fix before the demo, not during**.

- [ ] SSH to droplet: `ssh -i ~/.ssh/orca_deploy_key root@157.230.174.132`
- [ ] **Warm the v1 image:** `cd /opt/orca && docker-compose build`
- [ ] **Warm the v2 image:** `cd /opt/orca-v2 && docker-compose build`
- [ ] **Prove the switch actually takes 10s each way — run a full cycle:**
  ```
  demo-v1 && demo-v2 && demo-v1 && demo-v2
  ```
  Each `✅ v{1|2} live` line should appear within ~15s of the one above it. Longer = either a cache miss or a daemon hiccup — investigate now.
- [ ] Hit the dashboard in a browser — v2 should be live at this point. Verify:
  - Topology renders with gNBs + UPFs visible
  - Churn Forecast tab loads without errors
  - Inject Fault button is present and not stuck in a loading state
  - Security Watchlist shows the seeded `PE-02 unauthorized gNMI` entry
- [ ] Dry-run Act 1 end-to-end: Inject Fault → slice-A QoS → watch proposal appear → approve → verify churn count drops
- [ ] Dry-run Act 2 end-to-end: Inject Fault → transport congestion → approve workaround → verify TAC email appears in Email Outbox
- [ ] Clear state: `curl -X POST http://localhost/api/demo/reset && curl -X POST http://localhost/api/demo/security-reset && curl -X DELETE http://localhost/api/emails && curl -X DELETE http://localhost/api/config-proposals`
- [ ] Leave v2 running. Don't touch anything else until the PM briefing.

---

## Troubleshooting mid-demo

### Symptom: after `demo-v2`, browser loads blank / stale content

The JS bundle hash changed between v1 and v2 and the browser is serving cached HTML referencing a dead asset. Hard refresh (Ctrl+Shift+R, Cmd+Shift+R on Mac).

### Symptom: container starts but `/api/health` never returns

Usually means the FastAPI app crashed at startup (missing env var, import error, port conflict). Check:
```
docker logs orca-v2_api_1 --tail 50
```
Most common cause: the other stack didn't fully release port 80 before `up -d` tried to bind. Solution: `demo-v2` again — the `docker-compose down` at the top of the script will clean up the half-started container.

### Symptom: during a v2 demo, I'm not sure if the behavior I'm seeing is a v2 regression or a shared bug

Open a second SSH session and inspect v1 state side-by-side while v2 is serving:
```
# Session 1: v2 is running, serving port 80 from /opt/orca-v2
# Session 2: poke at v1's source without touching the container
cd /opt/orca && git log --oneline -5    # confirms v1 is still at v1.0.0
grep -r "<the suspicious behavior>" /opt/orca/agent/   # is it present in v1 too?
```
Don't `docker-compose up` v1 unless you're ready to swap — that'll drop v2.

### Rollback path (demo day worst case)

```
demo-v1
```
That's the whole procedure. v1.0.0 is tagged, has a passing E2E suite, and has been running stably. If v2 is broken and there's no time to fix, run one command and pitch the transport demo.

---

## GitHub PR hygiene

Both stacks push PRs to the same `sireenmalik/orca` repo. To keep the PR list readable:

- **v1 PRs** use branch prefix `cfg/R{…}-…` (existing convention) — no change.
- **v2 PRs** use branch prefix `cfg/v2-{…}-…` and are auto-labelled `demo-v2` via the PR template checkbox.

If you're scrolling the PR list and need to know which demo a PR came from, the branch name tells you at a glance, the label lets you filter.

---

## Tags on this branch

| Tag | Meaning |
|---|---|
| `v1.0.0` | Stable IP/MPLS demo (rollback point, always respected) |
| `v2.0.0-infra` | Demo v2 workspace + switch scripts in place; no 5G code yet |
| `v2.0.0-demo-5g` | 5G RAN demo verified end-to-end; set when section 8 polish is done |

Intermediate alpha / rc tags may appear during the build-up — those are checkpoints, not rollback targets.
