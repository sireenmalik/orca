#!/bin/bash
# ORCA demo reset — full state wipe via API. Command-line equivalent of
# clicking Reset in the UI. Safe to run anytime. Does not touch v1.
#
# Usage:
#   /opt/orca-v2/scripts/demo-reset.sh
set -u

BASE="http://localhost"

# Scenarios reset also clears v2 proposals, v2 emails, churn state, rogue
# config, adapter baseline, and broadcasts churn_updated / emails_cleared.
curl -s -X POST "$BASE/api/scenarios/reset" > /dev/null 2>&1

# Belt + suspenders — DELETE the v2 stores directly in case the scenarios
# reset above couldn't reach them (e.g. module import error in prod).
curl -s -X DELETE "$BASE/api/proposals" > /dev/null 2>&1

echo "Demo state reset · ready for next run"
