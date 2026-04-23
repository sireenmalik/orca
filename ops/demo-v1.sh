#!/bin/bash
# Switch the droplet to the v1.0.0 IP/MPLS transport demo on port 80.
# Safe to re-run; it will no-op on v2 if v2 is already stopped.
set -e

V1_DIR="/opt/orca"
V2_DIR="/opt/orca-v2"
HEALTH_URL="http://localhost/api/health"
MAX_WAIT_S=20

echo "→ stopping v2 (if running)"
cd "$V2_DIR" && docker-compose down 2>/dev/null || true

echo "→ starting v1"
cd "$V1_DIR" && docker-compose up -d

echo "→ waiting for port 80 to serve /api/health"
for i in $(seq 1 $MAX_WAIT_S); do
    resp=$(curl -s -f "$HEALTH_URL" 2>/dev/null || true)
    if echo "$resp" | grep -q '"status":"ok"'; then
        echo "✅ v1 live and responding on port 80 — $resp"
        docker ps --format '  {{.Names}} | {{.Status}}' | grep -E 'orca_api_1|orca-v2' || true
        exit 0
    fi
    sleep 1
done

echo "❌ v1 container started but /api/health not responding after ${MAX_WAIT_S}s"
docker ps --format '  {{.Names}} | {{.Status}}' | grep -E 'orca' || true
echo "→ tail of container logs:"
docker logs --tail 30 orca_api_1 2>&1 || true
exit 1
