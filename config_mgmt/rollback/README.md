# Rollback Checkpoints (NETCONF Discard-Changes)

Config snapshots saved before every push. Used for instant revert.

Equivalent to NETCONF **discard-changes** operation (RFC 6241 §7.5.7).

## Naming: {network}-{device}-checkpoint-{timestamp}.conf

## Triggered automatically when
- Post-push verification fails (utilization breach, LSP down)
- Operator manually triggers rollback from dashboard
- NETCONF commit returns error

## Retention: last 10 checkpoints per device
