#!/bin/bash
# Switch the droplet to the v2.x 5G RAN demo on port 80.
# Safe to re-run; it will no-op on v1 if v1 is already stopped.
set -e

V1_DIR="/opt/orca"
V2_DIR="/opt/orca-v2"
HEALTH_URL="http://localhost/api/health"
MAX_WAIT_S=20

echo "→ stopping v1 (if running)"
cd "$V1_DIR" && docker-compose down 2>/dev/null || true

# Also tear down any stale v2 container — docker-compose 1.29 hits a
# KeyError: 'ContainerConfig' bug on recreate when the image was rebuilt
# since the container was last started. Down + up dodges it.
echo "→ tearing down any stale v2 container"
cd "$V2_DIR" && docker-compose down 2>/dev/null || true

echo "→ starting v2"
cd "$V2_DIR" && docker-compose up -d

echo "→ waiting for port 80 to serve /api/health"
for i in $(seq 1 $MAX_WAIT_S); do
    resp=$(curl -s -f "$HEALTH_URL" 2>/dev/null || true)
    if echo "$resp" | grep -q '"status":"ok"'; then
        echo "✅ v2 live and responding on port 80 — $resp"
        docker ps --format '  {{.Names}} | {{.Status}}' | grep -E 'orca' || true
        exit 0
    fi
    sleep 1
done

echo "❌ v2 container started but /api/health not responding after ${MAX_WAIT_S}s"
docker ps --format '  {{.Names}} | {{.Status}}' | grep -E 'orca' || true
echo "→ tail of container logs:"
docker logs --tail 30 $(docker ps --filter name=orca-v2 --format '{{.Names}}' | head -1) 2>&1 || true
exit 1
