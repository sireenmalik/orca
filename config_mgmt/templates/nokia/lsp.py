# Nokia SR-OS Configuration Templates
# Format: MD-CLI / YANG model nokia-conf
# Target: SR-OS 22.x+
# Push via: NETCONF port 830

# ── LSP Template ──────────────────────────────────────────────────────────────
# Variables: {lsp_name}, {src}, {dst}, {bandwidth_mbps}, {path_nodes}

LSP_TEMPLATE = """
configure {
    router "Base" {
        mpls {
            lsp "{lsp_name}" {
                admin-state enable
                type p2p-rsvp
                to {dst_loopback}
                bandwidth {bandwidth_mbps}
                primary "{lsp_name}-primary" {
                    {explicit_hops}
                }
            }
            path "{lsp_name}-primary" {
                admin-state enable
                {path_hops}
            }
        }
    }
}
"""

# ── Explicit Hop Generator ─────────────────────────────────────────────────────
# Input: list of node loopbacks
# Output: RSVP-TE explicit hop config

HOP_TEMPLATE = """
hop {hop_index} {
    ip-address {loopback}
    type strict
}
"""

# ── Interface Metric Template ──────────────────────────────────────────────────
# For IGP metric adjustments (Mission 2 optimisation)

METRIC_TEMPLATE = """
configure {
    router "Base" {
        interface "{interface_name}" {
            ldp-sync-timer 10
            metric {metric_value}
        }
        isis {
            interface "{interface_name}" {
                level 2 {
                    metric {metric_value}
                }
            }
        }
    }
}
"""

# ── Rollback Checkpoint Template ──────────────────────────────────────────────
# Create a rollback checkpoint before any config push

CHECKPOINT_TEMPLATE = """
admin checkpoint create "{checkpoint_name}" comment "{comment}"
"""

# ── Validation Checks ─────────────────────────────────────────────────────────

def validate_lsp_config(config: str, topology: dict) -> dict:
    """
    Validate LSP config before push:
    - All hop IPs exist in topology
    - Bandwidth does not exceed link capacity
    - Path does not violate Mission 1
    """
    errors = []
    warnings = []
    # Implementation in config_mgmt/validators/nokia.py
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def render_lsp(lsp_spec: dict, network_spec: dict) -> str:
    """
    Render Nokia SR-OS LSP config from spec.
    Deterministic — same inputs always produce same output.
    """
    # Implementation in config_mgmt/renderers/nokia.py
    pass
