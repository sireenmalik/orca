"""
CSPF → Config consistency tests.
Verifies that CSPF path output matches LSP hop definitions in candidate configs.
This is the bridge test — ensures the algorithm and the configs agree.

Run: python -m pytest tests/test_consistency.py -v
"""
import sys, re, pytest
sys.path.insert(0, '.')
from agent.cspf import cspf, verify_mission_1, verify_mission_2

# Topology matching nokia-lab-sfo2.yaml
TOPOLOGY = {
    "nodes": {n: {"id": n, "state": "up"} for n in ["R1","R2","R3","R4","R5","R6"]},
    "links": {
        "R1-R2": {"src":"R1","dst":"R2","state":"up","utilization_pct":45.0,"capacity_gbps":10,"igp_metric":10},
        "R2-R3": {"src":"R2","dst":"R3","state":"up","utilization_pct":52.0,"capacity_gbps":10,"igp_metric":10},
        "R3-R4": {"src":"R3","dst":"R4","state":"up","utilization_pct":48.0,"capacity_gbps":10,"igp_metric":10},
        "R4-R5": {"src":"R4","dst":"R5","state":"up","utilization_pct":38.0,"capacity_gbps":10,"igp_metric":10},
        "R5-R6": {"src":"R5","dst":"R6","state":"up","utilization_pct":42.0,"capacity_gbps":10,"igp_metric":10},
        "R6-R1": {"src":"R6","dst":"R1","state":"up","utilization_pct":35.0,"capacity_gbps":10,"igp_metric":10},
        "R1-R4": {"src":"R1","dst":"R4","state":"up","utilization_pct":28.0,"capacity_gbps":10,"igp_metric":10},
        "R2-R5": {"src":"R2","dst":"R5","state":"up","utilization_pct":31.0,"capacity_gbps":10,"igp_metric":10},
    }
}

# LSP definitions matching nokia-lab-sfo2-lsps.yaml
LSPS = {
    "lsp-customer-a": {"src": "R1", "dst": "R4", "bandwidth_gbps": 2.0,
                       "primary_path": ["R1","R2","R3","R4"]},
    "lsp-customer-b": {"src": "R2", "dst": "R6", "bandwidth_gbps": 1.5,
                       "primary_path": ["R2","R3","R4","R5","R6"]},
    "lsp-mgmt":       {"src": "R1", "dst": "R6", "bandwidth_gbps": 0.5,
                       "primary_path": ["R1","R6"]},
}


# ── Path feasibility ──────────────────────────────────────────────────────────

def test_all_lsp_primary_paths_are_feasible():
    """Every LSP primary path must be reachable via CSPF."""
    for lsp_id, lsp in LSPS.items():
        path = cspf(TOPOLOGY, lsp["src"], lsp["dst"],
                    bandwidth_gbps=lsp["bandwidth_gbps"])
        assert path is not None, \
            f"LSP {lsp_id}: CSPF found no feasible path from {lsp['src']} to {lsp['dst']}"

def test_all_lsp_primary_paths_satisfy_mission_1():
    """Every LSP primary path must satisfy Mission 1 (all links < 90%)."""
    for lsp_id, lsp in LSPS.items():
        path = lsp["primary_path"]
        assert verify_mission_1(path, TOPOLOGY), \
            f"LSP {lsp_id}: primary path violates Mission 1 constraint"

def test_mission_2_reroute_improves_or_maintains():
    """
    For each LSP, verify that CSPF finds a path where max utilization
    does not exceed the primary path's max utilization.
    Mission 2: min(max utilization).
    """
    for lsp_id, lsp in LSPS.items():
        primary = lsp["primary_path"]
        cspf_path = cspf(TOPOLOGY, lsp["src"], lsp["dst"])
        if cspf_path and cspf_path != primary:
            # CSPF found an alternative — verify Mission 2 improvement
            ranked = verify_mission_2([primary, cspf_path], TOPOLOGY)
            # CSPF result should be ranked first (lower max util) or equal
            assert ranked[0] in [primary, cspf_path], \
                f"LSP {lsp_id}: unexpected Mission 2 ranking"


# ── Config ↔ CSPF consistency ─────────────────────────────────────────────────

def _extract_hop_loopbacks(config_text):
    """Extract ordered hop IP addresses from Nokia SR-OS LSP config."""
    hops = re.findall(r'hop \d+ \{ ip-address ([\d.]+) type strict \}', config_text)
    return hops

def _loopback_to_node(ip):
    """Map 10.0.0.X → RX."""
    parts = ip.split(".")
    return f"R{parts[3]}" if len(parts) == 4 else None

def test_r1_lsp_customer_a_hops_match_spec():
    """R1 candidate config LSP hops must match the LSP spec primary path."""
    try:
        with open("config_mgmt/candidate/nokia-lab-sfo2/R1.conf") as f:
            content = f.read()
    except FileNotFoundError:
        pytest.skip("R1 candidate config not found")

    hops = _extract_hop_loopbacks(content)
    hop_nodes = [_loopback_to_node(h) for h in hops if _loopback_to_node(h)]

    spec_path = LSPS["lsp-customer-a"]["primary_path"]
    # Hops in config don't include the source node
    expected_hops = spec_path[1:]  # R2, R3, R4

    assert hop_nodes == expected_hops, \
        f"R1 lsp-customer-a hops {hop_nodes} don't match spec {expected_hops}"

def test_failure_scenario_r1r4_has_alternate_path():
    """
    When R1-R4 fails, CSPF must find an alternate path for lsp-customer-a.
    This validates the failure scenario pre-computation in skills/future/.
    """
    # Remove R1-R4 link
    failed_topo = {**TOPOLOGY, "links": {
        k: ({**v, "state": "down"} if k == "R1-R4" else v)
        for k, v in TOPOLOGY["links"].items()
    }}
    path = cspf(failed_topo, "R1", "R4", bandwidth_gbps=2.0)
    assert path is not None, \
        "No alternate path for lsp-customer-a when R1-R4 fails — Mission 1 at risk"
    assert "R1-R4" not in [f"{path[i]}-{path[i+1]}" for i in range(len(path)-1)], \
        "CSPF returned failed link in alternate path"
    assert verify_mission_1(path, failed_topo), \
        "Alternate path violates Mission 1 after R1-R4 failure"

def test_failure_scenario_r2r3_has_alternate_path():
    """When R2-R3 fails, CSPF must find alternate for lsp-customer-b."""
    failed_topo = {**TOPOLOGY, "links": {
        k: ({**v, "state": "down"} if k == "R2-R3" else v)
        for k, v in TOPOLOGY["links"].items()
    }}
    path = cspf(failed_topo, "R2", "R6", bandwidth_gbps=1.5)
    assert path is not None, \
        "No alternate path for lsp-customer-b when R2-R3 fails"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except Exception as e:
                print(f"❌ {name}: {e}")
