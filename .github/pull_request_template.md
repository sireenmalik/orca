<!--
ORCA PR template. Tick the demo lineage box so the PR list stays scannable.
See DEMO_README.md for the full v1 vs v2 story.
-->

## Demo lineage

- [ ] `v1` — IP/MPLS transport ops (main / `v1.0.0`). Branch prefix `cfg/R{…}`.
- [ ] `v2` — 5G RAN demo (`demo/5g-ran`). Branch prefix `cfg/v2-…`. **Apply the `demo-v2` label on this PR.**
- [ ] Infra / shared — touches both stacks or neither.

## Summary

<!-- What changed and why in 2-3 lines. -->

## Test plan

- [ ] `ORCA_BASE_URL=http://localhost python3 -m pytest tests/test_e2e_baseline.py -v` still passes on v1
- [ ] Dry-run Act 1 + Act 2 from DEMO_README.md pre-flight on v2
- [ ] `demo-v1 && demo-v2` round-trip still <15s each
