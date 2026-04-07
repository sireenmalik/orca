"""
CSPF algorithm tests.
Run: python -m pytest tests/test_cspf.py -v
"""
import sys
sys.path.insert(0, '.')
from agent.cspf import cspf, k_shortest_paths, verify_mission_1, verify_mission_2

TOPOLOGY = {
    "nodes": {n: {"id": n, "state": "up"} for n in ["R1","R2","R3","R4","R5","R6"]},
    "links": {
        "R1-R2": {"src": "R1", "dst": "R2", "state": "up", "utilization_pct": 45.0, "capacity_gbps": 10, "igp_metric": 10},
        "R2-R3": {"src": "R2", "dst": "R3", "state": "up", "utilization_pct": 52.0, "capacity_gbps": 10, "igp_metric": 10},
        "R3-R4": {"src": "R3", "dst": "R4", "state": "up", "utilization_pct": 48.0, "capacity_gbps": 10, "igp_metric": 10},
        "R4-R5": {"src": "R4", "dst": "R5", "state": "up", "utilization_pct": 38.0, "capacity_gbps": 10, "igp_metric": 10},
        "R5-R6": {"src": "R5", "dst": "R6", "state": "up", "utilization_pct": 42.0, "capacity_gbps": 10, "igp_metric": 10},
        "R6-R1": {"src": "R6", "dst": "R1", "state": "up", "utilization_pct": 35.0, "capacity_gbps": 10, "igp_metric": 10},
        "R1-R4": {"src": "R1", "dst": "R4", "state": "up", "utilization_pct": 28.0, "capacity_gbps": 10, "igp_metric": 10},
        "R2-R5": {"src": "R2", "dst": "R5", "state": "up", "utilization_pct": 31.0, "capacity_gbps": 10, "igp_metric": 10},
    }
}

def test_basic_path():
    path = cspf(TOPOLOGY, "R1", "R4")
    assert path is not None
    assert path[0] == "R1"
    assert path[-1] == "R4"

def test_direct_path_preferred():
    path = cspf(TOPOLOGY, "R1", "R4")
    assert path == ["R1", "R4"]  # direct cross-link is shortest

def test_down_link_avoided():
    topo = {**TOPOLOGY, "links": {**TOPOLOGY["links"],
        "R1-R4": {**TOPOLOGY["links"]["R1-R4"], "state": "down"}}}
    path = cspf(topo, "R1", "R4")
    assert path is not None
    assert "R1-R4" not in [f"{path[i]}-{path[i+1]}" for i in range(len(path)-1)]

def test_mission_1():
    path = ["R1", "R4"]
    assert verify_mission_1(path, TOPOLOGY) == True

def test_k_paths():
    paths = k_shortest_paths(TOPOLOGY, "R1", "R4", k=3)
    assert len(paths) >= 1
    assert all(p[0] == "R1" and p[-1] == "R4" for p in paths)

def test_mission_2_ranking():
    paths = [["R1","R4"], ["R1","R2","R3","R4"]]
    ranked = verify_mission_2(paths, TOPOLOGY)
    assert ranked[0] == ["R1","R4"]  # lower max util

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except Exception as e:
                print(f"❌ {name}: {e}")
