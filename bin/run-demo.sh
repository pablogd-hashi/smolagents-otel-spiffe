#!/usr/bin/env bash
# Send a varied batch of HashiCorp / platform-engineering tasks to the planner.
#
# Task mix is deliberate:
#   * KB searches across Vault, Consul, Terraform, Nomad, observability, smolagents
#   * API calls to cluster_health, agent_telemetry, cost_estimate, lease_status
#   * One multi-step synthesis task to exercise planning_interval
#   * One task that triggers a tool error (top_k > 10)
#   * One task that triggers a sandbox error (banned import)
#   * One complex task likely to hit max_steps
#
# After this run every panel on the agent-operations dashboard should have data:
# throughput, latency, LLM token counts, tool call breakdown, and error rates.

set -euo pipefail

PLANNER_URL="${PLANNER_URL:-http://localhost:8000/run}"
SLEEP_BETWEEN="${SLEEP_BETWEEN:-2}"

tasks=(
  "Search the knowledge base for 'Vault dynamic secrets' and summarise the top result."
  "Call the cluster_health API and report whether Vault is sealed and how many Consul services are passing."
  "Search the knowledge base for 'Consul service mesh intentions' with top_k=5 and return all excerpts."
  "Get the current agent telemetry from the API and report the planner and executor p95 run durations."
  "Search the knowledge base for 'Terraform state backend' and explain the key recommendations."
  "Retrieve the Vault lease status from the API and flag any leases expiring within the hour."
  "Search the knowledge base for 'smolagents' with top_k=99 results."
  "Get the cost estimate from the API, then search the KB for 'smolagents step callbacks', then write a one-paragraph summary explaining how token costs relate to the observability approach described in the KB."
  "Run a Python snippet that calculates the number of unique Vault secret paths if there are 4 mount points each with 6 roles, without using import os."
  "Find three KB articles covering observability, distributed tracing, and Consul telemetry. For each article produce a one-sentence action item for a HashiCorp operator, then combine the three into a prioritised recommendation."
)

echo "Sending ${#tasks[@]} tasks to $PLANNER_URL ..."
for i in "${!tasks[@]}"; do
  task="${tasks[$i]}"
  echo "[$((i+1))/${#tasks[@]}] $task"
  resp=$(curl -fsS -X POST "$PLANNER_URL" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg t "$task" '{task: $t}')" \
    || echo '{"status":"http_error"}')
  status=$(echo "$resp" | jq -r '.status // "unknown"')
  echo "    -> status=$status"
  sleep "$SLEEP_BETWEEN"
done

echo
echo "Done. Open Grafana at http://localhost:3000 and view the 'Agent Operations' dashboard."
echo "Open Jaeger at http://localhost:16686 and pick a recent trace from service 'planner-agent'."
