"""
CSPF algorithm tests.
Run: python -m pytest tests/test_cspf.py -v
"""
import sys
sys.path.insert(0, '.')
from agent.cspf import cspf, k_shortest_paths, verify_mission_1, verify_mission_2

TOPOLOGY = {
    "nodes": {n: {"id": n, "state": "up"} for n in ["PE-01","P-02","PE-03","PE-04","P-01","PE-02"]},
    "links": {
        "PE-01-P-02": {"src": "PE-01", "dst": "P-02", "state": "up", "utilization_pct": 45.0, "capacity_gbps": 10, "igp_metric": 10},
        "P-02-PE-03": {"src": "P-02", "dst": "PE-03", "state": "up", "utilization_pct": 52.0, "capacity_gbps": 10, "igp_metric": 10},
        "PE-03-PE-04": {"src": "PE-03", "dst": "PE-04", "state": "up", "utilization_pct": 48.0, "capacity_gbps": 10, "igp_metric": 10},
        "PE-04-P-01": {"src": "PE-04", "dst": "P-01", "state": "up", "utilization_pct": 38.0, "capacity_gbps": 10, "igp_metric": 10},
        "P-01-PE-02": {"src": "P-01", "dst": "PE-02", "state": "up", "utilization_pct": 42.0, "capacity_gbps": 10, "igp_metric": 10},
        "PE-02-PE-01": {"src": "PE-02", "dst": "PE-01", "state": "up", "utilization_pct": 35.0, "capacity_gbps": 10, "igp_metric": 10},
        "PE-01-PE-04": {"src": "PE-01", "dst": "PE-04", "state": "up", "utilization_pct": 28.0, "capacity_gbps": 10, "igp_metric": 10},
        "P-02-P-01": {"src": "P-02", "dst": "P-01", "state": "up", "utilization_pct": 31.0, "capacity_gbps": 10, "igp_metric": 10},
    }
}

def test_basic_path():
    path = cspf(TOPOLOGY, "PE-01", "PE-04")
    assert path is not None
    assert path[0] == "PE-01"
    assert path[-1] == "PE-04"

def test_direct_path_preferred():
    path = cspf(TOPOLOGY, "PE-01", "PE-04")
    assert path == ["PE-01", "PE-04"]  # direct cross-link is shortest

def test_down_link_avoided():
    topo = {**TOPOLOGY, "links": {**TOPOLOGY["links"],
        "PE-01-PE-04": {**TOPOLOGY["links"]["PE-01-PE-04"], "state": "down"}}}
    path = cspf(topo, "PE-01", "PE-04")
    assert path is not None
    assert "PE-01-PE-04" not in [f"{path[i]}-{path[i+1]}" for i in range(len(path)-1)]

def test_mission_1():
    path = ["PE-01", "PE-04"]
    assert verify_mission_1(path, TOPOLOGY) == True

def test_k_paths():
    paths = k_shortest_paths(TOPOLOGY, "PE-01", "PE-04", k=3)
    assert len(paths) >= 1
    assert all(p[0] == "PE-01" and p[-1] == "PE-04" for p in paths)

def test_mission_2_ranking():
    paths = [["PE-01","PE-04"], ["PE-01","P-02","PE-03","PE-04"]]
    ranked = verify_mission_2(paths, TOPOLOGY)
    assert ranked[0] == ["PE-01","PE-04"]  # lower max util

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except Exception as e:
                print(f"❌ {name}: {e}")
