# ORCA DEMO — Operator Cheat Sheet

## Demo URL
**http://157.230.174.132**  ·  hard-refresh before each run: `Ctrl+Shift+R`

## Switching between v1 and v2
```
demo-v1    # v1.0.0 — transport-only baseline
demo-v2    # v2.0.0 — 5G RAN pivot
```
Currently running: **v2**

## Pre-demo checklist (60s)
```
cd /opt/orca-v2 && ./scripts/preflight.sh
```
If anything is WARN: click Reset in the Operations tab. If anything is FAIL: stop and fix.

---

## Act sequence

### Setup (before Inject)
> *"Nokia UPF cluster, UPF-01 + UPF-02. Enhanced mobile broadband slice A, 842 enterprise subscribers. 15 ms SLA. Currently green at 11 ms."*

---

### Act 1 (3 min) — UPF hero + churn drop

1. `Inject Fault → "Slice-A QoS degradation on UPF-01 (Act 1)"`
2. Narrate while the reasoning log streams (~10 s). Pause on the CONCLUDE: **"Dual root cause"**.
3. Proposal card materializes. *(optional: click it to show three-column modal briefly.)*
4. Click **Approve & Deploy**. Watch cascade.
5. **Immediately switch to Churn Forecast tab.** Deliver the line:
   > *"That's an operations action updating revenue risk in real time. Nobody else does this."*
6. At-risk subscribers animates **847 → 438**. Revenue at risk **$4.1M → $2.9M**.

---

### Act 2 (3 min) — Nokia core is innocent

1. Switch back to Operations. Click **Reset**.
2. `Inject Fault → "Transport congestion on LSP-1 (Act 2)"`
3. Watch the reasoning log. On CONCLUDE **"Nokia core is innocent"** — pause two full seconds.
   > *"Nokia TAC didn't burn a single hour on a fault that wasn't ours."*
4. Proposal card materializes → **Approve & Deploy**.
5. Email Outbox: amber-stripe TAC email appears. Click it.
6. Read aloud key lines from the email body: **evidence package, three suggested resolutions**.

---

### Act 3 (30 s) — Security teaser

1. Scroll **UP** in the reasoning log.
2. Point to the red **ALERT** entry (pre-seeded from earlier).
   > *"ORCA watches config state continuously. Often the first to see unauthorized changes. Not a security product — the earliest signal into one."*

*(Optional: click the `Inject Security Event (Act 3)` button to add a fresh ALERT live.)*

---

## If something breaks mid-demo

### Reasoning log stalls
> *"The reasoning loop runs in the background. In production this is sub-second; in the demo harness there's some network latency."*

Keep narrating.

### Churn forecast doesn't animate
> *"The churn count updates on a 30-second cycle. Let me keep going."*

Move on — don't wait.

### Fault injection button does nothing
In a terminal:
```
/opt/orca-v2/scripts/demo-reset.sh
```
Hard-refresh browser.
> *"Demo harness hiccup — let me show you what you'd have seen."*

Describe the flow verbally while recovering.

### Everything is broken
In a terminal:
```
demo-v1
```
Falls back to v1.0.0 transport demo in ~5 s.
> *"Let me show you the earlier version that's also running."*

---

## Tabs to pre-load
- **Operations** (main)
- **Churn Forecast** (pre-open in a second tab, keep alive so the animation lands first-paint)

---

## Post-briefing cleanup
```
python3 /opt/orca-v2/scripts/cleanup_prs.py --close-all-by-prefix v2/cfg/
```
Closes the PRs created during the live demo. Run this **after** screenshots if you want to keep any as audit examples.

---

## Contacts if things explode
- **Slack**: #orca-demo (Le)
- **Droplet SSH**: `ssh -i ~/.ssh/orca_deploy_key root@157.230.174.132`
- **GitHub repo**: `github.com/sireenmalik/orca` (private)
