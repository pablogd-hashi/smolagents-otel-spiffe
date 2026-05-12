#!/usr/bin/env bash
# Register the planner and executor services with Consul, then generate Envoy
# bootstrap configs for their sidecars.
#
# In a real deployment this would run inside each agent container as part of
# its entrypoint. Here we run it once from the host so the bootstrap configs
# are baked into a shared volume the sidecar containers mount.

set -euo pipefail

CONSUL_ADDR="${CONSUL_ADDR:-http://localhost:8500}"
SIDECAR_DIR="$(cd "$(dirname "$0")/.."; pwd)/consul/sidecars"
mkdir -p "$SIDECAR_DIR"

echo "Waiting for Consul at $CONSUL_ADDR ..."
for _ in $(seq 1 30); do
  if curl -fs "$CONSUL_ADDR/v1/status/leader" > /dev/null; then
    echo "Consul is up."
    break
  fi
  sleep 1
done

register_service() {
  local name="$1"
  local file="$2"

  echo "Registering $name from $file"
  curl -fsS -X PUT --data-binary @"$file" \
    "$CONSUL_ADDR/v1/agent/service/register?replace-existing-checks=true" \
    > /dev/null

  echo "Generating Envoy bootstrap for $name"
  docker compose exec -T consul \
    consul connect envoy \
      -bootstrap \
      -sidecar-for "$name-1" \
      -admin-bind 0.0.0.0:19000 \
      > "$SIDECAR_DIR/${name#*-}-bootstrap.yaml" || {
        echo "WARN: bootstrap generation failed for $name. Sidecar will fail to start."
      }
}

# Convert HCL service definitions to JSON for the API. Consul accepts HCL only
# via the CLI, so we use a small jq translation here.
hcl_to_json() {
  local hcl="$1"
  docker compose exec -T consul \
    consul services format -format=json -content "$(cat "$hcl")" 2>/dev/null \
    || cat "$hcl"  # fallback: HCL is also accepted by /v1/agent/service/register on newer consul
}

# Use the consul CLI inside the container to register the HCL files directly
docker compose cp agents/planner/consul-service.hcl  consul:/tmp/planner.hcl
docker compose cp agents/executor/consul-service.hcl consul:/tmp/executor.hcl

docker compose exec -T consul consul services register /tmp/planner.hcl
docker compose exec -T consul consul services register /tmp/executor.hcl

echo "Generating Envoy bootstrap configs..."
docker compose exec -T consul \
  consul connect envoy -bootstrap -sidecar-for planner-agent-1 -admin-bind 0.0.0.0:19000 \
  > "$SIDECAR_DIR/planner-bootstrap.yaml"

docker compose exec -T consul \
  consul connect envoy -bootstrap -sidecar-for executor-agent-1 -admin-bind 0.0.0.0:19000 \
  > "$SIDECAR_DIR/executor-bootstrap.yaml"

# Post-process the generated bootstraps to fix two issues that arise because
# the sidecars run in a different network namespace than the consul container:
#
# 1. Port conflict: Consul puts both the admin endpoint AND the prometheus
#    metrics listener on port 19000. Move the metrics listener to 19001.
#
# 2. Local agent address: The bootstrap uses 127.0.0.1:8503 (TLS gRPC) to
#    reach Consul for xDS config. In the planner/executor network namespace
#    there is no consul at localhost. Switch to consul:8502 (plain gRPC, which
#    is available in dev mode) and drop the TLS transport socket.
python3 - "$SIDECAR_DIR/planner-bootstrap.yaml" "$SIDECAR_DIR/executor-bootstrap.yaml" <<'PYEOF'
import json, sys
for path in sys.argv[1:]:
    with open(path) as f:
        d = json.load(f)
    sr = d.get("static_resources", {})
    # Fix 1: move prometheus metrics listener off the admin port
    for listener in sr.get("listeners", []):
        if listener.get("name") == "envoy_prometheus_metrics_listener":
            listener["address"]["socket_address"]["port_value"] = 19001
    # Fix 2: point local_agent at consul:8502 (plain gRPC, no TLS).
    # STATIC type requires a literal IP; switch to STRICT_DNS so Envoy
    # resolves the "consul" hostname via the container's DNS.
    for cluster in sr.get("clusters", []):
        if cluster.get("name") == "local_agent":
            cluster["type"] = "STRICT_DNS"
            for ep in cluster.get("loadAssignment", {}).get("endpoints", []):
                for lb in ep.get("lbEndpoints", []):
                    sa = lb["endpoint"]["address"]["socket_address"]
                    sa["address"] = "consul"
                    sa["port_value"] = 8502
            cluster.pop("transport_socket", None)
            cluster.get("typed_extension_protocol_options", {}).pop(
                "envoy.extensions.upstreams.http.v3.HttpProtocolOptions", None
            )
    with open(path, "w") as f:
        json.dump(d, f)
PYEOF

echo "Sidecar bootstraps written to $SIDECAR_DIR"
