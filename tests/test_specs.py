"""
Spec validation tests.
Validates all YAML spec files for correctness before any config is generated.

Run: python -m pytest tests/test_specs.py -v
"""
import sys, os, yaml, pytest
sys.path.insert(0, '.')

SPECS_DIR = "specs"
NETWORK_SPEC = "specs/network/nokia-lab-sfo2.yaml"
LSP_SPEC     = "specs/lsp/nokia-lab-sfo2-lsps.yaml"
POLICY_SPEC  = "specs/policy/nokia-lab-sfo2-policy.yaml"

def load_yaml_body(path):
    """Load YAML file, stripping the --- frontmatter header."""
    with open(path) as f:
        content = f.read()
    # Strip frontmatter
    parts = content.split("---")
    for part in parts[2:]:
        try:
            # Find the first valid YAML code block
            if "```yaml" in part:
                block = part.split("```yaml")[1].split("```")[0]
                return yaml.safe_load(block)
        except: pass
    return {}


# ── Network spec tests ────────────────────────────────────────────────────────

def test_network_spec_exists():
    assert os.path.exists(NETWORK_SPEC), f"Missing: {NETWORK_SPEC}"

def test_network_spec_has_nodes():
    data = load_yaml_body(NETWORK_SPEC)
    nodes = data.get("nodes", {})
    assert len(nodes) >= 2, "Network must have at least 2 nodes"

def test_network_spec_has_links():
    data = load_yaml_body(NETWORK_SPEC)
    links = data.get("links", {})
    assert len(links) >= 1, "Network must have at least 1 link"

def test_network_links_reference_valid_nodes():
    data = load_yaml_body(NETWORK_SPEC)
    nodes = set(data.get("nodes", {}).keys())
    links = data.get("links", {})
    for link_id, link in links.items():
        assert link["src"] in nodes, f"Link {link_id}: src '{link['src']}' not in nodes"
        assert link["dst"] in nodes, f"Link {link_id}: dst '{link['dst']}' not in nodes"

def test_network_constraints_present():
    data = load_yaml_body(NETWORK_SPEC)
    c = data.get("constraints", {})
    assert "max_link_utilization_pct" in c, "Missing Mission 1 constraint"
    assert c["max_link_utilization_pct"] <= 100
    assert c["max_link_utilization_pct"] > 0

def test_mission_1_threshold_is_90():
    """Mission 1 hard constraint must be 90%."""
    data = load_yaml_body(NETWORK_SPEC)
    c = data.get("constraints", {})
    assert c.get("max_link_utilization_pct") == 90, \
        f"Mission 1 threshold must be 90%, got {c.get('max_link_utilization_pct')}"


# ── LSP spec tests ────────────────────────────────────────────────────────────

def test_lsp_spec_exists():
    assert os.path.exists(LSP_SPEC), f"Missing: {LSP_SPEC}"

def test_lsp_paths_reference_valid_nodes():
    net_data = load_yaml_body(NETWORK_SPEC)
    lsp_data = load_yaml_body(LSP_SPEC)
    nodes = set(net_data.get("nodes", {}).keys())
    lsps = lsp_data.get("lsps", {})
    for lsp_id, lsp in lsps.items():
        path = lsp.get("primary_path", {}).get("explicit", [])
        for node in path:
            assert node in nodes, \
                f"LSP {lsp_id}: node '{node}' in path not in topology"

def test_lsp_src_dst_in_nodes():
    net_data = load_yaml_body(NETWORK_SPEC)
    lsp_data = load_yaml_body(LSP_SPEC)
    nodes = set(net_data.get("nodes", {}).keys())
    lsps = lsp_data.get("lsps", {})
    for lsp_id, lsp in lsps.items():
        assert lsp["src"] in nodes, f"LSP {lsp_id}: src not in topology"
        assert lsp["dst"] in nodes, f"LSP {lsp_id}: dst not in topology"

def test_lsp_path_is_contiguous():
    """Every hop in an LSP path must be adjacent in the topology."""
    net_data = load_yaml_body(NETWORK_SPEC)
    lsp_data = load_yaml_body(LSP_SPEC)
    links = net_data.get("links", {})
    # Build adjacency set
    adj = set()
    for l in links.values():
        adj.add((l["src"], l["dst"]))
        adj.add((l["dst"], l["src"]))
    lsps = lsp_data.get("lsps", {})
    for lsp_id, lsp in lsps.items():
        path = lsp.get("primary_path", {}).get("explicit", [])
        for i in range(len(path) - 1):
            pair = (path[i], path[i+1])
            assert pair in adj, \
                f"LSP {lsp_id}: no link between {path[i]} and {path[i+1]}"

def test_lsp_bandwidth_positive():
    lsp_data = load_yaml_body(LSP_SPEC)
    for lsp_id, lsp in lsp_data.get("lsps", {}).items():
        assert lsp.get("bandwidth_gbps", 0) > 0, \
            f"LSP {lsp_id}: bandwidth must be positive"


# ── Policy spec tests ─────────────────────────────────────────────────────────

def test_policy_spec_exists():
    assert os.path.exists(POLICY_SPEC), f"Missing: {POLICY_SPEC}"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except Exception as e:
                print(f"❌ {name}: {e}")
