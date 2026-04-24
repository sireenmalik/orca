#!/bin/bash
# ORCA DEMO PREFLIGHT — runs before rehearsal or the PM briefing.
# Eight checks, each PASS / WARN / FAIL. Exit 0 if all PASS (or only
# WARN), exit 1 if any FAIL. Target runtime: under 60 seconds.
#
# Usage:
#   cd /opt/orca-v2 && ./scripts/preflight.sh

set -u

BASE="http://localhost"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
PASS_STR="${GREEN}PASS${RESET}"
WARN_STR="${YELLOW}WARN${RESET}"
FAIL_STR="${RED}FAIL${RESET}"

FAILS=0
WARNS=0

# pretty-print a check line (width 34 for the label)
_row() {
    local n=$1 label=$2 status=$3 note=$4
    printf "[%d] %-34s %b  %s\n" "$n" "$label" "$status" "$note"
}

echo "==========="
echo "ORCA DEMO PREFLIGHT — $(date -u '+%Y-%m-%d %H:%M:%SZ')"
echo ""

# ── Check 1: v2 container running ──
CONTAINER=$(docker ps --format '{{.Names}} {{.Status}}' | grep orca-v2_api_1 || true)
if [[ -n "$CONTAINER" ]]; then
    _row 1 "Container running" "$PASS_STR" "$(echo "$CONTAINER" | sed 's/orca-v2_api_1 //')"
else
    _row 1 "Container running" "$FAIL_STR" "orca-v2_api_1 not found"
    FAILS=$((FAILS+1))
fi

# ── Check 2: API health ──
HEALTH=$(curl -s -m 3 "$BASE/api/health" 2>/dev/null || true)
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    _row 2 "API health" "$PASS_STR" ""
else
    _row 2 "API health" "$FAIL_STR" "/api/health returned: ${HEALTH:-<no response>}"
    FAILS=$((FAILS+1))
fi

# ── Check 3: Topology (10 nodes, 2 LSPs, 2 slices) ──
STATE=$(curl -s -m 3 "$BASE/api/state" 2>/dev/null || echo '{}')
TOPO_REPORT=$(python3 - <<PYEOF 2>/dev/null
import json, sys
try:
    d = json.loads("""$STATE""")
except Exception:
    print("FAIL:could not parse /api/state"); sys.exit(0)
nodes = d.get("nodes", {})
lsps  = d.get("lsps", {})
slices = d.get("slices", {})
required_nodes = {"gNB-1","gNB-2","PE-01","PE-02","PE-03","PE-04","P-01","P-02","UPF-01","UPF-02"}
required_lsps = {"LSP-1","LSP-2"}
required_slices = {"slice-A","slice-B"}
missing_nodes = required_nodes - set(nodes.keys())
missing_lsps  = required_lsps  - set(lsps.keys())
missing_slices = required_slices - set(slices.keys())
problems = []
if missing_nodes: problems.append(f"missing nodes: {sorted(missing_nodes)}")
if missing_lsps:  problems.append(f"missing LSPs: {sorted(missing_lsps)}")
if missing_slices: problems.append(f"missing slices: {sorted(missing_slices)}")
if problems: print("FAIL:" + "; ".join(problems))
else: print(f"PASS:{len(nodes)} nodes, {len(lsps)} LSPs ({','.join(sorted(required_lsps))}), {len(slices)} slices")
PYEOF
)
TOPO_STATUS=${TOPO_REPORT%%:*}
TOPO_NOTE=${TOPO_REPORT#*:}
if [[ "$TOPO_STATUS" == "PASS" ]]; then
    _row 3 "Topology" "$PASS_STR" "$TOPO_NOTE"
else
    _row 3 "Topology" "$FAIL_STR" "$TOPO_NOTE"
    FAILS=$((FAILS+1))
fi

# ── Check 4: Scenarios registered ──
SCEN_IDS=$(curl -s -m 3 "$BASE/api/scenarios" 2>/dev/null | python3 -c 'import sys,json;
try: d=json.load(sys.stdin); print(",".join(s["id"] for s in d.get("scenarios",[])))
except: print("")' 2>/dev/null)
if echo "$SCEN_IDS" | grep -q "slice-a-qos-drift" && echo "$SCEN_IDS" | grep -q "transport-congestion-upf-innocent"; then
    _row 4 "Scenarios registered" "$PASS_STR" "slice-a-qos-drift, transport-congestion-upf-innocent"
else
    _row 4 "Scenarios registered" "$FAIL_STR" "got: ${SCEN_IDS:-<none>}"
    FAILS=$((FAILS+1))
fi

# ── Check 5: Baseline state (no pending proposals / emails) ──
PROPOSAL_COUNT=$(curl -s -m 3 "$BASE/api/proposals" 2>/dev/null | python3 -c 'import sys,json;
try: print(len(json.load(sys.stdin).get("proposals",[])))
except: print(0)' 2>/dev/null)
EMAIL_COUNT=$(curl -s -m 3 "$BASE/api/v2/emails" 2>/dev/null | python3 -c 'import sys,json;
try: print(len(json.load(sys.stdin).get("emails",[])))
except: print(0)' 2>/dev/null)
if [[ "$PROPOSAL_COUNT" == "0" && "$EMAIL_COUNT" == "0" ]]; then
    _row 5 "Baseline state" "$PASS_STR" "0 proposals, 0 emails"
else
    _row 5 "Baseline state" "$WARN_STR" "$PROPOSAL_COUNT proposal(s), $EMAIL_COUNT email(s) — click Reset before demo"
    WARNS=$((WARNS+1))
fi

# ── Check 6: Frontend bundle hash ──
BUNDLE=$(curl -s -m 3 "$BASE/" 2>/dev/null | grep -oE 'index-[a-z0-9]+\.js' | head -1)
HASH_FILE="/opt/orca-v2/.demo-hash"
if [[ -n "$BUNDLE" ]]; then
    EXPECTED=""
    if [[ -f "$HASH_FILE" ]]; then EXPECTED=$(cat "$HASH_FILE"); fi
    if [[ -n "$EXPECTED" && "$BUNDLE" != "$EXPECTED" ]]; then
        _row 6 "Frontend bundle" "$WARN_STR" "current=$BUNDLE, expected=$EXPECTED"
        WARNS=$((WARNS+1))
    else
        _row 6 "Frontend bundle" "$PASS_STR" "$BUNDLE"
    fi
else
    _row 6 "Frontend bundle" "$FAIL_STR" "could not read bundle hash from /"
    FAILS=$((FAILS+1))
fi

# ── Check 7: GitHub token ──
TOKEN=""
if [[ -f "/opt/orca-v2/.env" ]]; then
    TOKEN=$(grep '^GITHUB_TOKEN=' /opt/orca-v2/.env | head -1 | cut -d= -f2- | tr -d '"')
fi
if [[ -z "$TOKEN" ]]; then
    _row 7 "GitHub token" "$FAIL_STR" "GITHUB_TOKEN not set in /opt/orca-v2/.env"
    FAILS=$((FAILS+1))
else
    GH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -m 5 \
        -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/user" 2>/dev/null)
    if [[ "$GH_STATUS" == "200" ]]; then
        _row 7 "GitHub token" "$PASS_STR" "api.github.com/user 200 OK"
    else
        _row 7 "GitHub token" "$FAIL_STR" "api.github.com/user returned $GH_STATUS — PR creation will break"
        FAILS=$((FAILS+1))
    fi
fi

# ── Check 8: v1 not serving ──
V1_RUNNING=$(docker ps --format '{{.Names}}' | grep -E '^orca_api_1$' || true)
if [[ -z "$V1_RUNNING" ]]; then
    _row 8 "v1 not serving" "$PASS_STR" "orca_api_1 is stopped"
else
    _row 8 "v1 not serving" "$FAIL_STR" "orca_api_1 is running — run demo-v2 to switch"
    FAILS=$((FAILS+1))
fi

# ── Summary ──
echo ""
if [[ $FAILS -gt 0 ]]; then
    echo -e "RESULT: ${RED}FAILED${RESET} ($FAILS)"
    if [[ $WARNS -gt 0 ]]; then echo "        plus $WARNS warning(s)"; fi
    exit 1
elif [[ $WARNS -gt 0 ]]; then
    echo -e "RESULT: ${YELLOW}READY WITH WARNING${RESET} ($WARNS)"
    exit 0
else
    echo -e "RESULT: ${GREEN}READY${RESET}"
    exit 0
fi
