# Deployed Configs

Last confirmed config running on each production device.
Updated only after successful NETCONF push + verification.
Never edited manually.

## Rollback
```bash
python -m config_mgmt.push --device R1 --rollback
```
