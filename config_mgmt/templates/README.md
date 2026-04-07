# Config Templates

Parameterised config fragments per vendor. Input to the renderer.

## Structure
```
templates/
  nokia/    — Nokia SR-OS MD-CLI / YANG
  cisco/    — Cisco IOS-XR YANG
  juniper/  — Juniper Junos XML
```

## Renderer
```bash
python -m config_mgmt.renderers.nokia \
  --spec specs/network/nokia-lab-sfo2.yaml \
  --lsp specs/lsp/nokia-lab-sfo2-lsps.yaml \
  --output config_mgmt/candidate/nokia-lab-sfo2/
```

Templates are deterministic — same spec always produces identical output.
