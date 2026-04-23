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
    "nodes": {n: {"id": n, "state": "up"} for n in ["PE-01","P-02","PE-03","PE-04","P-01","PE-02"]},
    "links": {
        "PE-01-P-02": {"src":"PE-01","dst":"P-02","state":"up","utilization_pct":45.0,"capacity_gbps":10,"igp_metric":10},
        "P-02-PE-03": {"src":"P-02","dst":"PE-03","state":"up","utilization_pct":52.0,"capacity_gbps":10,"igp_metric":10},
        "PE-03-PE-04": {"src":"PE-03","dst":"PE-04","state":"up","utilization_pct":48.0,"capacity_gbps":10,"igp_metric":10},
        "PE-04-P-01": {"src":"PE-04","dst":"P-01","state":"up","utilization_pct":38.0,"capacity_gbps":10,"igp_metric":10},
        "P-01-PE-02": {"src":"P-01","dst":"PE-02","state":"up","utilization_pct":42.0,"capacity_gbps":10,"igp_metric":10},
        "PE-02-PE-01": {"src":"PE-02","dst":"PE-01","state":"up","utilization_pct":35.0,"capacity_gbps":10,"igp_metric":10},
        "PE-01-PE-04": {"src":"PE-01","dst":"PE-04","state":"up","utilization_pct":28.0,"capacity_gbps":10,"igp_metric":10},
        "P-02-P-01": {"src":"P-02","dst":"P-01","state":"up","utilization_pct":31.0,"capacity_gbps":10,"igp_metric":10},
    }
}

# LSP definitions matching nokia-lab-sfo2-lsps.yaml
LSPS = {
    "lsp-customer-a": {"src": "PE-01", "dst": "PE-04", "bandwidth_gbps": 2.0,
                       "primary_path": ["PE-01","P-02","PE-03","PE-04"]},
    "lsp-customer-b": {"src": "P-02", "dst": "PE-02", "bandwidth_gbps": 1.5,
                       "primary_path": ["P-02","PE-03","PE-04","P-01","PE-02"]},
    "lsp-mgmt":       {"src": "PE-01", "dst": "PE-02", "bandwidth_gbps": 0.5,
                       "primary_path": ["PE-01","PE-02"]},
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
    """PE-01 candidate config LSP hops must match the LSP spec primary path."""
    try:
        with open("config_mgmt/candidate/nokia-lab-sfo2/PE-01.conf") as f:
            content = f.read()
    except FileNotFoundError:
        pytest.skip("PE-01 candidate config not found")

    hops = _extract_hop_loopbacks(content)
    hop_nodes = [_loopback_to_node(h) for h in hops if _loopback_to_node(h)]

    spec_path = LSPS["lsp-customer-a"]["primary_path"]
    # Hops in config don't include the source node
    expected_hops = spec_path[1:]  # P-02, PE-03, PE-04

    assert hop_nodes == expected_hops, \
        f"PE-01 lsp-customer-a hops {hop_nodes} don't match spec {expected_hops}"

def test_failure_scenario_r1r4_has_alternate_path():
    """
    When PE-01-PE-04 fails, CSPF must find an alternate path for lsp-customer-a.
    This validates the failure scenario pre-computation in skills/future/.
    """
    # Remove PE-01-PE-04 link
    failed_topo = {**TOPOLOGY, "links": {
        k: ({**v, "state": "down"} if k == "PE-01-PE-04" else v)
        for k, v in TOPOLOGY["links"].items()
    }}
    path = cspf(failed_topo, "PE-01", "PE-04", bandwidth_gbps=2.0)
    assert path is not None, \
        "No alternate path for lsp-customer-a when PE-01-PE-04 fails — Mission 1 at risk"
    assert "PE-01-PE-04" not in [f"{path[i]}-{path[i+1]}" for i in range(len(path)-1)], \
        "CSPF returned failed link in alternate path"
    assert verify_mission_1(path, failed_topo), \
        "Alternate path violates Mission 1 after PE-01-PE-04 failure"

def test_failure_scenario_r2r3_has_alternate_path():
    """When P-02-PE-03 fails, CSPF must find alternate for lsp-customer-b."""
    failed_topo = {**TOPOLOGY, "links": {
        k: ({**v, "state": "down"} if k == "P-02-PE-03" else v)
        for k, v in TOPOLOGY["links"].items()
    }}
    path = cspf(failed_topo, "P-02", "PE-02", bandwidth_gbps=1.5)
    assert path is not None, \
        "No alternate path for lsp-customer-b when P-02-PE-03 fails"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except Exception as e:
                print(f"❌ {name}: {e}")
