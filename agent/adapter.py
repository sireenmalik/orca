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
    Simulated 6-node ring topology for demo.
    Swap NETWORK_ADAPTER env var to use production adapters.
    """

    TOPOLOGY = {
        "nodes": {
            "R1": Node("R1", "10.0.0.1", "up", "core"),
            "R2": Node("R2", "10.0.0.2", "up", "core"),
            "R3": Node("R3", "10.0.0.3", "up", "core"),
            "R4": Node("R4", "10.0.0.4", "up", "core"),
            "R5": Node("R5", "10.0.0.5", "up", "core"),
            "R6": Node("R6", "10.0.0.6", "up", "core"),
        },
        "links": {
            "R1-R2": Link("R1-R2", "R1", "R2", "eth1", "eth1", 10.0),
            "R2-R3": Link("R2-R3", "R2", "R3", "eth2", "eth1", 10.0),
            "R3-R4": Link("R3-R4", "R3", "R4", "eth2", "eth1", 10.0),
            "R4-R5": Link("R4-R5", "R4", "R5", "eth2", "eth1", 10.0),
            "R5-R6": Link("R5-R6", "R5", "R6", "eth2", "eth1", 10.0),
            "R6-R1": Link("R6-R1", "R6", "R1", "eth2", "eth2", 10.0),
            "R1-R4": Link("R1-R4", "R1", "R4", "eth3", "eth3", 10.0),
            "R2-R5": Link("R2-R5", "R2", "R5", "eth3", "eth3", 10.0),
        }
    }

    LSP_DEFAULTS = {
        "lsp-customer-a": LSP("lsp-customer-a", "Customer-A Primary", "R1", "R4",
                              ["R1","R2","R3","R4"], 2.0),
        "lsp-customer-b": LSP("lsp-customer-b", "Customer-B Primary", "R2", "R6",
                              ["R2","R3","R4","R5","R6"], 1.5),
        "lsp-mgmt":       LSP("lsp-mgmt", "Management", "R1", "R6",
                              ["R1","R6"], 0.5),
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
            "R1-R2": 35.0, "R2-R3": 40.0, "R3-R4": 38.0,
            "R4-R5": 28.0, "R5-R6": 32.0, "R6-R1": 25.0,
            "R1-R4": 22.0, "R2-R5": 24.0
        }

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
                          "metric": self._metrics.get(k, 10)}
                      for k, v in self._links.items()}
        }

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
            "R1-R2": 35.0, "R2-R3": 40.0, "R3-R4": 38.0,
            "R4-R5": 28.0, "R5-R6": 32.0, "R6-R1": 25.0,
            "R1-R4": 22.0, "R2-R5": 24.0
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
        return NetworkState(
            nodes=topo["nodes"], links=topo["links"],
            lsps={l["id"]: l for l in lsps}, alarms=alarms
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
            from agent.adapter import Alarm
            import time
            alarm = Alarm(id=f"alarm-{int(time.time())}", severity="critical" if utilization >= 90 else "major",
                          node=self._links[link_id].src_node,
                          description=f"Link {link_id} utilization at {utilization:.0f}% — threshold exceeded")
            self._alarms.append(alarm)
        return {"success": True, "link_id": link_id, "old_util": round(old, 1), "new_util": utilization}
