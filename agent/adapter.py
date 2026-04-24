"""
ORCA Network Adapter
ContainerlabAdapter: simulated 6-node topology for demo.
Replace with NokiaAdapter, CiscoAdapter etc for production.
"""

import asyncio
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    id: str
    loopback: str
    state: str = "up"
    role: str = "core"

@dataclass
class Link:
    id: str
    src_node: str
    dst_node: str
    src_iface: str
    dst_iface: str
    capacity_gbps: float = 10.0
    state: str = "up"
    utilization_pct: float = 0.0

@dataclass
class LSP:
    id: str
    name: str
    src: str
    dst: str
    path: list
    bandwidth_gbps: float = 1.0
    state: str = "up"

@dataclass
class Alarm:
    id: str
    severity: str
    node: str
    description: str
    cleared: bool = False

@dataclass
class NetworkState:
    nodes: dict
    links: dict
    lsps: dict
    alarms: list
    slices: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)
    qer_state: dict = field(default_factory=dict)
    slice_metrics: dict = field(default_factory=dict)
    link_flags: dict = field(default_factory=dict)


class NetworkAdapter(ABC):
    @abstractmethod
    async def get_topology(self) -> dict: pass
    @abstractmethod
    async def get_link_utilization(self, link_id: str = None) -> dict: pass
    @abstractmethod
    async def get_lsp_state(self) -> list: pass
    @abstractmethod
    async def get_alarms(self) -> list: pass
    @abstractmethod
    async def reroute_lsp(self, lsp_id: str, new_path: list) -> dict: pass
    @abstractmethod
    async def set_link_metric(self, link_id: str, metric: int) -> dict: pass
    @abstractmethod
    async def simulate_failure(self, link_id: str) -> dict: pass
    @abstractmethod
    async def restore_link(self, link_id: str) -> dict: pass
    @abstractmethod
    async def get_full_state(self) -> NetworkState: pass


class ContainerlabAdapter(NetworkAdapter):
    """
    Simulated end-to-end 5G topology for demo v2:
      RAN (gNBs, left) → MPLS transport (PE/P mesh, middle) → 5G core (UPFs, right)

    Node roles drive frontend styling:
      ran   — gNodeB (radio accent + antenna icon)
      upf   — User Plane Function (core accent, server icon)
      edge  — MPLS edge router (PE-xx)
      core  — MPLS P router (P-xx)

    Link role = "stub" means "endpoint connects to an edge via a single
    stub interface" — rendered thinner/dashed. Transport mesh links have
    no role set (default).

    Swap NETWORK_ADAPTER env var to use production adapters.
    """

    TOPOLOGY = {
        "nodes": {
            # ── RAN (stubs into PE-01 and PE-02) ──
            "gNB-1":  Node("gNB-1",  "10.1.0.1", "up", "ran"),
            "gNB-2":  Node("gNB-2",  "10.1.0.2", "up", "ran"),
            # ── MPLS transport ──
            "PE-01": Node("PE-01", "10.0.0.1", "up", "edge"),
            "P-02":  Node("P-02",  "10.0.0.2", "up", "core"),
            "PE-03": Node("PE-03", "10.0.0.3", "up", "edge"),
            "PE-04": Node("PE-04", "10.0.0.4", "up", "edge"),
            "P-01":  Node("P-01",  "10.0.0.5", "up", "core"),
            "PE-02": Node("PE-02", "10.0.0.6", "up", "edge"),
            # ── 5G core (stubs off PE-03 and PE-04) ──
            "UPF-01": Node("UPF-01", "10.2.0.1", "up", "upf"),
            "UPF-02": Node("UPF-02", "10.2.0.2", "up", "upf"),
        },
        "links": {
            # Transport mesh (unchanged from Phase 1A rename)
            "PE-01-P-02":  Link("PE-01-P-02",  "PE-01", "P-02",  "eth1", "eth1", 10.0),
            "P-02-PE-03":  Link("P-02-PE-03",  "P-02",  "PE-03", "eth2", "eth1", 10.0),
            "PE-03-PE-04": Link("PE-03-PE-04", "PE-03", "PE-04", "eth2", "eth1", 10.0),
            "PE-04-P-01":  Link("PE-04-P-01",  "PE-04", "P-01",  "eth2", "eth1", 10.0),
            "P-01-PE-02":  Link("P-01-PE-02",  "P-01",  "PE-02", "eth2", "eth1", 10.0),
            "PE-02-PE-01": Link("PE-02-PE-01", "PE-02", "PE-01", "eth2", "eth2", 10.0),
            "PE-01-PE-04": Link("PE-01-PE-04", "PE-01", "PE-04", "eth3", "eth3", 10.0),
            "P-02-P-01":   Link("P-02-P-01",   "P-02",  "P-01",  "eth3", "eth3", 10.0),
            # Stub links — RAN to PE and UPF to PE (thinner/dashed in UI)
            "gNB-1-PE-01":  Link("gNB-1-PE-01",  "gNB-1",  "PE-01", "n3",    "eth4", 10.0),
            "gNB-2-PE-02":  Link("gNB-2-PE-02",  "gNB-2",  "PE-02", "n3",    "eth4", 10.0),
            "UPF-01-PE-03": Link("UPF-01-PE-03", "UPF-01", "PE-03", "n3",    "eth4", 10.0),
            "UPF-02-PE-04": Link("UPF-02-PE-04", "UPF-02", "PE-04", "n3",    "eth4", 10.0),
        }
    }

    # Links whose endpoint is a stub (ran or upf). Rendered differently on
    # the topology and excluded from CSPF / transport reroute logic.
    STUB_LINKS = {"gNB-1-PE-01", "gNB-2-PE-02", "UPF-01-PE-03", "UPF-02-PE-04"}

    LSP_DEFAULTS = {
        # v2 demo LSPs — anchor the slice narrative.
        # LSP-1: gNB-1 → PE-01 → P-02 → PE-03 → UPF-01 (slice A, enterprise)
        # LSP-2: gNB-2 → PE-02 → P-01 → PE-04 → UPF-02 (slice B, consumer)
        "LSP-1": LSP("LSP-1", "slice-A enterprise path", "PE-01", "PE-03",
                     ["PE-01", "P-02", "PE-03"], 2.0),
        "LSP-2": LSP("LSP-2", "slice-B consumer path",  "PE-02", "PE-04",
                     ["PE-02", "P-01", "PE-04"], 1.5),
        # v1 LSPs — still referenced by v1 baseline tests; kept for backward-
        # compat until the v2 E2E suite replaces test_e2e_baseline.py.
        "lsp-customer-a": LSP("lsp-customer-a", "Customer-A Primary", "PE-01", "PE-04",
                              ["PE-01","P-02","PE-03","PE-04"], 2.0),
        "lsp-customer-b": LSP("lsp-customer-b", "Customer-B Primary", "P-02", "PE-02",
                              ["P-02","PE-03","PE-04","P-01","PE-02"], 1.5),
        "lsp-mgmt":       LSP("lsp-mgmt", "Management", "PE-01", "PE-02",
                              ["PE-01","PE-02"], 0.5),
    }

    # ── 5G slice data model ───────────────────────────────────────────
    # Drives churn cohorts, SLA evaluation, reasoning log vocabulary.
    SLICES = {
        "slice-A": {
            "id": "slice-A",
            "name": "Enterprise eMBB",
            "cohort": "enterprise",
            "subscribers": 842,
            "gnb": "gNB-1",
            "upf": "UPF-01",
            "lsp": "LSP-1",
            "sla_latency_ms": 15,        # SLA threshold on one-way N3 latency
            "current_latency_ms": 11.0,  # green at baseline
            "arpu_usd": 1200,            # annual revenue per subscriber
        },
        "slice-B": {
            "id": "slice-B",
            "name": "Consumer eMBB",
            "cohort": "consumer",
            "subscribers": 15000,
            "gnb": "gNB-2",
            "upf": "UPF-02",
            "lsp": "LSP-2",
            "sla_latency_ms": 50,
            "current_latency_ms": 28.0,
            "arpu_usd": 30,
        },
    }

    # Baseline PDU session distribution per UPF. Aggregate counters —
    # individual session objects are not modeled (demo performance).
    SESSIONS_BASELINE = {
        "UPF-01": {
            "total": 612,
            "by_slice": {"slice-A": 612, "slice-B": 0},
            "by_gnb":   {"gNB-1": 612,   "gNB-2": 0},
            "high_bw_sessions": 180,  # priority-class count, used by PFCP rebalance demo
        },
        "UPF-02": {
            "total": 8243,
            "by_slice": {"slice-A": 0, "slice-B": 8243},
            "by_gnb":   {"gNB-1": 0,   "gNB-2": 8243},
            "high_bw_sessions": 40,
        },
    }

    # Approved baseline configs (what should be on each router)
    APPROVED_CONFIGS = {
        "PE-01": {
            "isis_metrics": {"to-P-02": 10, "to-PE-02": 10, "to-PE-04": 15},
            "snmp_communities": ["public-read-only"],
            "bgp_neighbors": [],
            "acl_rules": ["permit established", "deny any log"],
            "logging": "enabled",
        },
        "P-02": {
            "isis_metrics": {"to-PE-01": 10, "to-PE-03": 10, "to-P-01": 15},
            "snmp_communities": ["public-read-only"],
            "bgp_neighbors": [],
            "acl_rules": ["permit established", "deny any log"],
            "logging": "enabled",
        },
        "PE-03": {
            "isis_metrics": {"to-P-02": 10, "to-PE-04": 10},
            "snmp_communities": ["public-read-only"],
            "bgp_neighbors": [],
            "acl_rules": ["permit established", "deny any log"],
            "logging": "enabled",
        },
    }

    def __init__(self):
        self._nodes = {k: Node(v.id, v.loopback, v.state, v.role)
                       for k, v in self.TOPOLOGY["nodes"].items()}
        self._links = {k: Link(v.id, v.src_node, v.dst_node, v.src_iface,
                               v.dst_iface, v.capacity_gbps)
                       for k, v in self.TOPOLOGY["links"].items()}
        self._lsps = {k: LSP(v.id, v.name, v.src, v.dst, list(v.path), v.bandwidth_gbps)
                      for k, v in self.LSP_DEFAULTS.items()}
        self._alarms: list = []
        self._metrics = {lid: 10 for lid in self._links}
        self._start_time = time.time()
        self._base_util = {
            # Transport mesh
            "PE-01-P-02": 35.0, "P-02-PE-03": 40.0, "PE-03-PE-04": 38.0,
            "PE-04-P-01": 28.0, "P-01-PE-02": 32.0, "PE-02-PE-01": 25.0,
            "PE-01-PE-04": 22.0, "P-02-P-01": 24.0,
            # Stubs — light load, cosmetic only
            "gNB-1-PE-01":  18.0, "gNB-2-PE-02":  16.0,
            "UPF-01-PE-03": 22.0, "UPF-02-PE-04": 20.0,
        }
        # Security: rogue config injection flag
        self._rogue_config: dict = {}  # node -> list of rogue changes
        # Churn: LSP utilization history (96 slots = 24h at 15min intervals)
        self._lsp_history: dict = {lsp_id: [] for lsp_id in self.LSP_DEFAULTS}
        self._history_tick = 0
        # 5G slice + session state (mutable — reroute/rebalance updates these)
        self._slices = {sid: dict(s) for sid, s in self.SLICES.items()}
        self._sessions = {
            upf: {
                "total":              data["total"],
                "by_slice":           dict(data["by_slice"]),
                "by_gnb":             dict(data["by_gnb"]),
                "high_bw_sessions":   data["high_bw_sessions"],
            }
            for upf, data in self.SESSIONS_BASELINE.items()
        }
        # v2 scenario playback — populated by scenarios.apply_scenario_patch
        # Sparse dicts; when empty, the frontend treats them as "no signal
        # on this dimension" and the baseline KPIs render.
        self._qer_state:     dict = {}   # {upf: {slice: {intent_gbr_mbps, enforced_mbps, status}}}
        self._slice_metrics: dict = {}   # {upf: {slice_key: {p99_ms, ...}}} or LSP-side
        self._link_flags:    dict = {}   # {link_id: {microbursts: bool, ...}}

    def inject_rogue_config(self, node: str = "PE-01") -> dict:
        """Simulate an unauthorized config change pushed directly to a router."""
        rogue = {
            "node": node,
            "changes": [
                {
                    "type": "rogue_addition",
                    "parameter": "snmp-community",
                    "value": "0p3r4t0r-rw",
                    "access": "read-write",
                    "description": "SNMP read-write community string — not in approved config",
                    "severity": "critical",
                    "classification": "management_plane_exposure",
                },
                {
                    "type": "rogue_addition",
                    "parameter": "acl",
                    "value": "permit ip any any",
                    "description": "Overly permissive ACL rule appended — bypasses deny-all",
                    "severity": "critical",
                    "classification": "access_control_weakening",
                }
            ],
            "injected_at": time.time(),
            "source_ip": "10.0.3.44",
            "method": "NETCONF direct push — no ORCA PR",
        }
        self._rogue_config[node] = rogue
        return rogue

    def clear_rogue_config(self) -> None:
        self._rogue_config.clear()

    async def get_running_config(self, node: str) -> dict:
        """Return running config for a node — includes any injected rogue changes."""
        approved = self.APPROVED_CONFIGS.get(node, {})
        running = {k: list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v
                   for k, v in approved.items()}
        rogue = self._rogue_config.get(node)
        if rogue:
            for ch in rogue["changes"]:
                param = ch["parameter"]
                if param == "snmp-community":
                    running.setdefault("snmp_communities", []).append(ch["value"])
                elif param == "acl":
                    running.setdefault("acl_rules", []).append(ch["value"])
        running["_has_rogue"] = bool(rogue)
        running["_rogue_meta"] = rogue
        return running

    async def get_approved_config(self, node: str) -> dict:
        """Return the approved baseline config for a node (from Git spec)."""
        return dict(self.APPROVED_CONFIGS.get(node, {}))

    def record_lsp_utilization(self, lsp_id: str, util_pct: float, rerouted: bool = False):
        """Add a utilization sample to the LSP history ring buffer."""
        history = self._lsp_history.setdefault(lsp_id, [])
        history.append({
            "ts": time.time(),
            "util": util_pct,
            "rerouted": rerouted,
        })
        # Keep 96 samples max (~24h at 15min intervals)
        if len(history) > 96:
            history.pop(0)

    def get_lsp_history(self, lsp_id: str, window: int = 96) -> list:
        """Return last N utilization samples for an LSP."""
        return self._lsp_history.get(lsp_id, [])[-window:]

    def _dynamic_util(self, link_id: str) -> float:
        base = self._base_util.get(link_id, 40.0)
        t = time.time() - self._start_time
        noise = 3.0 * math.sin(t * 0.1 + hash(link_id) % 10)
        return max(0.0, min(99.0, base + noise))

    async def get_topology(self) -> dict:
        return {
            "nodes": {k: {"id": v.id, "loopback": v.loopback,
                          "state": v.state, "role": v.role}
                      for k, v in self._nodes.items()},
            "links": {k: {"id": v.id, "src": v.src_node, "dst": v.dst_node,
                          "capacity_gbps": v.capacity_gbps, "state": v.state,
                          "metric": self._metrics.get(k, 10),
                          "is_stub": k in self.STUB_LINKS}
                      for k, v in self._links.items()}
        }

    def get_slices(self) -> dict:
        """Current 5G slice state — subscribers, cohort, SLA, current latency."""
        return {sid: dict(s) for sid, s in self._slices.items()}

    def get_qer_state(self) -> dict:
        """QER enforcement state per UPF, per slice. Populated by v2 scenarios."""
        return {upf: {s: dict(v) for s, v in per_slice.items()}
                for upf, per_slice in self._qer_state.items()}

    def get_slice_metrics(self) -> dict:
        """Per-UPF / per-LSP metrics (p99 latency etc). Populated by scenarios."""
        return {k: (dict(v) if isinstance(v, dict) else v)
                for k, v in self._slice_metrics.items()}

    def get_link_flags(self) -> dict:
        """Per-link boolean flags (microbursts etc). Populated by scenarios."""
        return {lid: dict(v) for lid, v in self._link_flags.items()}

    # ── v2 scenario patch applier — dotted-path mutator ────────────────
    # Scenarios target paths like "sessions.UPF-01.by_slice.slice-A" or
    # "qer_state.UPF-01.slice-A" or "alarms". This keeps the scenario
    # file declarative without teaching it about adapter internals.
    _SCENARIO_ROOTS = {
        "sessions":   "_sessions",
        "qer_state":  "_qer_state",
        "metrics":    "_slice_metrics",
        "link_flags": "_link_flags",
        "link_util":  "_base_util",   # scenarios set baseline util, dynamic layer still adds noise
        "alarms":     "_alarms",
    }

    def apply_scenario_patch(self, target: str, op: str, value) -> None:
        """Apply a single state mutation. ``target`` is a dotted path
        rooted at one of _SCENARIO_ROOTS. ``op`` is one of 'set',
        'increment', 'append'. ``append`` only works on list targets
        (currently only 'alarms').

        Creates intermediate dicts as needed so scenarios can introduce
        new per-UPF or per-slice keys without a schema migration.
        """
        parts = target.split(".")
        if not parts:
            return
        root_name = self._SCENARIO_ROOTS.get(parts[0])
        if not root_name:
            return
        container = getattr(self, root_name)

        # alarms: list with special-case append-of-Alarm handling
        if parts[0] == "alarms":
            if op == "append" and isinstance(value, dict):
                alarm = Alarm(
                    id          = value.get("id", f"scenario-{int(time.time()*1000)}"),
                    severity    = value.get("severity", "info"),
                    node        = value.get("node", ""),
                    description = value.get("description", ""),
                )
                self._alarms.append(alarm)
            return

        # Walk/create intermediate dicts
        cur = container
        rest = parts[1:]
        for key in rest[:-1]:
            if not isinstance(cur, dict):
                return
            if key not in cur or not isinstance(cur[key], dict):
                cur[key] = {}
            cur = cur[key]
        if not rest:
            # target is the root itself — not supported (root is always dict)
            return
        leaf = rest[-1]
        if not isinstance(cur, dict):
            return

        if op == "set":
            cur[leaf] = value
        elif op == "increment":
            try:
                cur[leaf] = (cur.get(leaf) or 0) + value
            except TypeError:
                cur[leaf] = value
        elif op == "append":
            if leaf not in cur or not isinstance(cur[leaf], list):
                cur[leaf] = []
            cur[leaf].append(value)

    def get_sessions(self) -> dict:
        """Aggregate PDU session counters per UPF (per-slice, per-gNB breakdown)."""
        return {upf: {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}
                for upf, data in self._sessions.items()}

    async def get_link_utilization(self, link_id: str = None) -> dict:
        if link_id:
            link = self._links.get(link_id)
            if not link:
                return {"error": f"Link {link_id} not found"}
            util = 0.0 if link.state == "down" else self._dynamic_util(link_id)
            return {link_id: {"utilization_pct": round(util, 1),
                              "capacity_gbps": link.capacity_gbps,
                              "state": link.state}}
        return {lid: {"utilization_pct": round(0.0 if self._links[lid].state == "down"
                                               else self._dynamic_util(lid), 1),
                      "capacity_gbps": self._links[lid].capacity_gbps,
                      "state": self._links[lid].state}
                for lid in self._links}

    async def get_lsp_state(self) -> list:
        return [{"id": v.id, "name": v.name, "src": v.src, "dst": v.dst,
                 "path": v.path, "bandwidth_gbps": v.bandwidth_gbps, "state": v.state}
                for v in self._lsps.values()]

    async def get_alarms(self) -> list:
        return [{"id": a.id, "severity": a.severity, "node": a.node,
                 "description": a.description}
                for a in self._alarms if not a.cleared]

    async def reroute_lsp(self, lsp_id: str, new_path: list) -> dict:
        lsp = self._lsps.get(lsp_id)
        if not lsp:
            return {"error": f"LSP {lsp_id} not found"}
        old_path = list(lsp.path)
        lsp.path = new_path
        self.record_lsp_utilization(lsp_id, 85.0, rerouted=True)
        return {"success": True, "lsp_id": lsp_id, "old_path": old_path,
                "new_path": new_path, "message": f"LSP {lsp_id} rerouted"}

    async def set_link_metric(self, link_id: str, metric: int) -> dict:
        if link_id not in self._metrics:
            return {"error": f"Link {link_id} not found"}
        old = self._metrics[link_id]
        self._metrics[link_id] = metric
        return {"success": True, "link_id": link_id, "old_metric": old, "new_metric": metric}

    async def simulate_failure(self, link_id: str) -> dict:
        link = self._links.get(link_id)
        if not link:
            return {"success": False, "error": f"Link {link_id} not found"}
        link.state = "down"
        link.utilization_pct = 0.0
        adjacent = self._find_adjacent_links(link_id)
        for adj_id in adjacent:
            self._base_util[adj_id] = min(88.0, self._base_util.get(adj_id, 40) + 45)
        alarm = Alarm(id=f"alarm-{int(time.time())}", severity="critical",
                      node=f"{link.src_node}/{link.dst_node}",
                      description=f"Link {link_id} DOWN — traffic impact on adjacent links")
        self._alarms.append(alarm)
        return {"success": True, "link_id": link_id, "state": "down",
                "alarm_id": alarm.id, "message": f"Link {link_id} failure injected"}

    async def restore_link(self, link_id: str) -> dict:
        link = self._links.get(link_id)
        if not link:
            return {"success": False, "error": f"Link {link_id} not found"}
        link.state = "up"
        link.utilization_pct = 0.0
        baseline = {
            "PE-01-P-02": 35.0, "P-02-PE-03": 40.0, "PE-03-PE-04": 38.0,
            "PE-04-P-01": 28.0, "P-01-PE-02": 32.0, "PE-02-PE-01": 25.0,
            "PE-01-PE-04": 22.0, "P-02-P-01": 24.0
        }
        self._base_util[link_id] = baseline.get(link_id, 40.0)
        adjacent = self._find_adjacent_links(link_id)
        for adj_id in adjacent:
            if self._base_util.get(adj_id, 0) > 80:
                self._base_util[adj_id] = baseline.get(adj_id, 40.0)
        for alarm in self._alarms:
            if link_id in alarm.node or link_id in alarm.description:
                alarm.cleared = True
        return {"success": True, "link_id": link_id, "state": "up",
                "message": f"Link {link_id} restored to baseline"}

    async def get_full_state(self) -> NetworkState:
        topo = await self.get_topology()
        utils = await self.get_link_utilization()
        lsps = await self.get_lsp_state()
        alarms = await self.get_alarms()
        for lid, u in utils.items():
            if lid in topo["links"]:
                topo["links"][lid]["utilization_pct"] = u["utilization_pct"]
        # Record LSP utilization samples for churn model
        for lsp in lsps:
            lsp_id = lsp["id"]
            path = lsp.get("path", [])
            path_utils = [utils.get(f"{path[i]}-{path[i+1]}", utils.get(f"{path[i+1]}-{path[i]}", {})).get("utilization_pct", 0)
                         for i in range(len(path)-1)]
            max_path_util = max(path_utils) if path_utils else 0
            self.record_lsp_utilization(lsp_id, max_path_util)
        return NetworkState(
            nodes=topo["nodes"], links=topo["links"],
            lsps={l["id"]: l for l in lsps}, alarms=alarms,
            slices=self.get_slices(), sessions=self.get_sessions(),
            qer_state=self.get_qer_state(),
            slice_metrics=self.get_slice_metrics(),
            link_flags=self.get_link_flags(),
        )

    def _find_adjacent_links(self, link_id: str) -> list:
        link = self._links.get(link_id)
        if not link:
            return []
        adj = []
        for lid, l in self._links.items():
            if lid == link_id:
                continue
            if l.src_node in [link.src_node, link.dst_node] or \
               l.dst_node in [link.src_node, link.dst_node]:
                adj.append(lid)
        return adj

    async def inject_congestion(self, link_id: str, utilization: float) -> dict:
        if link_id not in self._base_util:
            return {"success": False, "error": f"Link {link_id} not found"}
        old = self._base_util[link_id]
        self._base_util[link_id] = utilization
        if utilization > 80:
            alarm = Alarm(id=f"alarm-{int(time.time())}", severity="critical" if utilization >= 90 else "major",
                          node=self._links[link_id].src_node,
                          description=f"Link {link_id} utilization at {utilization:.0f}% — threshold exceeded")
            self._alarms.append(alarm)
        return {"success": True, "link_id": link_id, "old_util": round(old, 1), "new_util": utilization}
