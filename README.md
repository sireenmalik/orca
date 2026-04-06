# ORCA — Autonomous Network Operations & Response Agent

AI-native network operations platform. Monitors IP/MPLS networks, enforces traffic engineering objectives, generates and pushes vendor configs, and communicates autonomously with ops teams and vendors.

---

## Architecture

```
orca/
├── skills/
│   ├── persistent/     # Hard constraints, safety rules, objective functions (immutable)
│   ├── past/           # Episodic memory — learned from outcomes (grows over time)
│   └── future/         # Scenario plans, pre-computed responses (updated nightly)
│
├── specs/
│   ├── network/        # Network topology specs (YAML) — source of truth
│   ├── lsp/            # LSP definitions and policies
│   └── policy/         # Operator rules, notification config, autonomy level
│
├── agent/
│   ├── orca_agent.py   # Main reasoning loop (Claude Sonnet 4)
│   ├── cspf.py         # CSPF path computation algorithm
│   └── memory.py       # Three-layer memory loader
│
├── adapters/
│   ├── base.py         # NetworkAdapter abstract interface
│   ├── containerlab.py # Demo adapter (simulated)
│   ├── nokia.py        # Nokia SR-OS via gNMI/NETCONF
│   ├── cisco.py        # Cisco IOS-XR via gNMI/NETCONF
│   └── juniper.py      # Juniper Junos via NETCONF
│
├── config_mgmt/
│   ├── templates/      # Vendor config templates (Nokia, Cisco, Juniper)
│   ├── renderers/      # Spec → config renderers
│   ├── validators/     # Pre-push validation
│   └── diff/           # Desired vs running config diff engine
│
├── memory/
│   ├── episodic/       # Past action records (YAML + DB index)
│   ├── instructional/  # Operator rules loaded at runtime
│   └── learned/        # Preference models built from outcomes
│
├── api/
│   └── main.py         # FastAPI backend + WebSocket
│
├── dashboard/
│   └── src/App.jsx     # React + D3 real-time dashboard
│
└── tests/              # Spec validation, adapter tests, CSPF tests
```

---

## Objective Functions

**Mission 1 — Feasibility (hard constraint)**
```
∀ link l : utilization(l) < 90%
```

**Mission 2 — Optimality (objective)**
```
min( max utilization across all links )
```

---

## Decision Architecture

| Task | Method | Rationale |
|---|---|---|
| Path computation | CSPF algorithm | Provably optimal, sub-millisecond |
| Candidate selection | ORCA reasoning | Business context, operator policy, history |
| Config generation | Vendor templates | Deterministic, reproducible |
| Decision to act | ORCA reasoning | Judgment, novel fault handling |
| Verification | Math threshold checks | Objective, unambiguous |

---

## Vendor Support

| Vendor | Telemetry | Config Push | Status |
|---|---|---|---|
| Nokia SR-OS | gNMI | NETCONF | In development |
| Cisco IOS-XR | gNMI | NETCONF/gRPC | Planned |
| Juniper Junos | gNMI/JTI | NETCONF | Planned |
| Containerlab | Simulated | Simulated | ✅ Demo ready |

---

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/orca.git
cd orca

# Configure
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY, network adapter, SMTP config

# Point at your network
export NETWORK_ADAPTER=nokia          # or containerlab, cisco, juniper
export NETWORK_SPEC=specs/network/nokia-lab-sfo2.yaml

# Run
docker-compose up -d

# Dashboard
open http://localhost
```

---

## Reproducibility

Every deployment is fully reproducible from specs alone:

```bash
# Regenerate all configs from specs
python -m config_mgmt.renderers.render --spec specs/network/nokia-lab-sfo2.yaml

# Validate all specs
python -m tests.validate_specs

# Run CSPF against all failure scenarios
python -m agent.cspf --spec specs/network/nokia-lab-sfo2.yaml --scenario all-failures

# Diff desired vs running config
python -m config_mgmt.diff --device R1 --spec specs/lsp/nokia-lab-sfo2-lsps.yaml
```

---

## Branching Strategy

```
main          ← production-ready, tagged releases
develop       ← integration branch
feature/*     ← new features
fix/*         ← bug fixes
scenario/*    ← new scenario specs and pre-computed plans
adapter/*     ← new vendor adapter development
```

Config specs follow the same branching — a new LSP spec goes through `feature/lsp-customer-c`, reviewed, merged to develop, tested, merged to main, and then pushed to production.

---

## Memory Layers

| Layer | Contents | Updated |
|---|---|---|
| Persistent | Safety rules, objective functions | Never (requires code review) |
| Past | Episode records, outcomes, overrides | After every action cycle |
| Future | Scenario plans, pre-computed paths | Nightly planning cycle |

---

## Built With

- **Reasoning**: Claude Sonnet 4 (Anthropic)
- **Path computation**: CSPF (custom implementation)
- **Backend**: FastAPI + WebSocket
- **Dashboard**: React + D3
- **Config push**: NETCONF / gRPC
- **Telemetry**: gNMI / OpenConfig
- **Infrastructure**: DigitalOcean / any cloud or on-prem
