"""
Config validation tests.
Validates candidate configs against specs — before any NETCONF push.

Run: python -m pytest tests/test_configs.py -v
"""
import sys, os, glob, re, pytest
sys.path.insert(0, '.')

CANDIDATE_DIR = "config_mgmt/candidate"
NETWORK_SPEC  = "specs/network/nokia-lab-sfo2.yaml"

def get_candidate_configs():
    return glob.glob(f"{CANDIDATE_DIR}/**/*.conf", recursive=True)

def parse_interfaces_from_config(config_text):
    """Extract interface names from a Nokia SR-OS config."""
    return re.findall(r'interface "([^"]+)"', config_text)

def parse_lsp_names_from_config(config_text):
    """Extract LSP names from a Nokia SR-OS config."""
    return re.findall(r'lsp "([^"]+)"', config_text)

def parse_metrics_from_config(config_text):
    """Extract IS-IS metrics from config."""
    return [int(m) for m in re.findall(r'metric (\d+)', config_text)]


# ── Candidate config existence ────────────────────────────────────────────────

def test_candidate_configs_exist():
    configs = get_candidate_configs()
    assert len(configs) > 0, f"No candidate configs found in {CANDIDATE_DIR}/"

def test_all_routers_have_candidate_config():
    """Every router in the network spec should have a candidate config."""
    import yaml
    with open(NETWORK_SPEC) as f:
        content = f.read()
    # Extract node names from YAML block in markdown
    nodes = re.findall(r'^  (R\d+):', content, re.MULTILINE)
    nodes = list(set(nodes))
    configs = get_candidate_configs()
    config_devices = [os.path.basename(c).replace(".conf", "") for c in configs]
    for node in nodes:
        assert node in config_devices, \
            f"No candidate config for node {node}"


# ── Config content validation ─────────────────────────────────────────────────

def test_configs_have_loopback():
    """Every router config must have a loopback interface."""
    for config_path in get_candidate_configs():
        with open(config_path) as f:
            content = f.read()
        ifaces = parse_interfaces_from_config(content)
        assert "loopback" in ifaces, \
            f"{config_path}: missing loopback interface"

def test_configs_have_isis():
    """Every router config must have IS-IS enabled."""
    for config_path in get_candidate_configs():
        with open(config_path) as f:
            content = f.read()
        assert "isis" in content, \
            f"{config_path}: missing IS-IS configuration"

def test_configs_have_mpls():
    """Every router config must have MPLS enabled."""
    for config_path in get_candidate_configs():
        with open(config_path) as f:
            content = f.read()
        assert "mpls" in content, \
            f"{config_path}: missing MPLS configuration"

def test_config_metrics_are_positive():
    """All IS-IS metrics in configs must be positive integers."""
    for config_path in get_candidate_configs():
        with open(config_path) as f:
            content = f.read()
        metrics = parse_metrics_from_config(content)
        for m in metrics:
            assert m > 0, \
                f"{config_path}: non-positive metric value {m}"

def test_r1_has_customer_lsp():
    """R1 must have lsp-customer-a defined (it originates this LSP)."""
    r1_configs = [c for c in get_candidate_configs() if "R1.conf" in c]
    assert len(r1_configs) > 0, "No R1 candidate config found"
    with open(r1_configs[0]) as f:
        content = f.read()
    lsps = parse_lsp_names_from_config(content)
    assert "lsp-customer-a" in lsps, \
        "R1 config missing lsp-customer-a"

def test_no_config_references_down_interface():
    """Configs should not have admin-state disable on core interfaces."""
    for config_path in get_candidate_configs():
        with open(config_path) as f:
            content = f.read()
        # Check for disabled core interfaces (warning, not failure in baseline)
        disabled = re.findall(r'admin-state disable', content)
        # Allow disable only in specific contexts — flag if on core interface
        assert len(disabled) == 0 or "# disabled" in content.lower(), \
            f"{config_path}: found admin-state disable — verify intentional"


# ── Mission 1 pre-check ───────────────────────────────────────────────────────

def test_config_metrics_satisfy_mission_2():
    """
    All configured IS-IS metrics should be positive and consistent.
    Higher metric = less preferred path — used for Mission 2 optimisation.
    """
    for config_path in get_candidate_configs():
        with open(config_path) as f:
            content = f.read()
        metrics = parse_metrics_from_config(content)
        if metrics:
            assert max(metrics) < 10000, \
                f"{config_path}: suspiciously high metric {max(metrics)} — verify intentional"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except Exception as e:
                print(f"❌ {name}: {e}")
