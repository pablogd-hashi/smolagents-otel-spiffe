# Troubleshooting

## Stack startup

**`task up` hangs after "Generating Envoy bootstrap configs..."**
The Consul container has not finished electing a leader. Run `docker compose logs consul` and re-run `task up` after the container shows `agent: Synced node info`.

**`planner` or `executor` container restarting immediately**
Almost always a missing or invalid LLM API key. Check with:
```sh
docker compose logs planner | head -50
```
Verify `.env` contains a valid `OPENAI_API_KEY` (or your provider's equivalent), then restart:
```sh
docker compose restart planner executor
```

**Sidecar containers fail with "no such file or directory"**
The Envoy bootstrap configs were not generated. Run:
```sh
bash bin/register-services.sh
docker compose up -d planner-sidecar executor-sidecar
```

**otel-collector shows "connection refused" in agent logs**
The Collector starts after the agents in some orderings. The agents retry the gRPC connection automatically; wait 10–15 seconds and check `docker compose logs otel-collector`.

## Observability data

**Grafana shows "No data" on every panel**
The Collector hasn't started exporting yet, or the agents have not received any requests. Run `task health` to confirm everything is green, then `task demo` to generate traffic. Metrics export on a 10-second interval, so panels may be empty for the first 10–15 seconds after traffic begins.

**No traces in Jaeger but metrics work**
Tail sampling is dropping low-volume baseline traffic. Send 10+ tasks via `task demo` so the 5% baseline policy fires, or temporarily lower `decision_wait` in `otel-collector/config.yaml`.

**LLM / Token Economics panels empty**
Token counts come from `ActionStep.model_output_message.raw.usage`. If the model provider does not return usage data, or if the LiteLLM model ID is not mapped correctly, these will be null. Check `docker compose logs planner` for `_token_counts returned (None, None)` warnings.

**Audit logs not appearing in Loki panel**
The `agent.audit` Python logger must have the OTel `LoggingHandler` attached. This is done in `init_telemetry()`. If logs are missing, confirm the `otel-collector` container is healthy and that the Loki datasource in Grafana points to `http://loki:3100`.

**Agent Memory panels show wrong agent name**
The `$agent` variable is populated from `label_values(agent_run_total, agent)`. Agent names in metrics use dashes (`planner-agent`), matching the service name format. If you see underscores, the agent container was started before the label normalisation fix was applied — rebuild the image:
```sh
docker compose build planner executor
docker compose up -d planner executor
```

## Consul mesh

**`consul intention list` shows no intentions**
Terraform did not apply successfully. Re-run:
```sh
cd terraform && terraform apply -auto-approve
```

**Envoy sidecar logs show "upstream connect error"**
The target agent container may not be healthy, or the intention is missing. Check:
```sh
docker compose logs planner-sidecar | tail -30
consul intention list
```

## General tips

- `task health` — checks all container statuses and HTTP endpoints.
- `docker compose ps` — quick overview of what's running.
- `docker compose logs <service> -f` — follow logs for a specific container.
- Grafana's Explore view (left sidebar) lets you run raw PromQL and LogQL queries to diagnose missing data.
