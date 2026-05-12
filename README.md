# Watching the Agents Work

Companion repo for the Medium post *"Watching the Agents Work: Observability for AI Workloads in a Zero-Trust Mesh."*

A planner / executor agent pair built on smolagents, with full three-signal observability (traces → Jaeger, metrics → Prometheus, logs → Loki) and a Consul Connect service mesh with mTLS enforced by Vault PKI.

## Prerequisites

- Docker + Docker Compose v2
- [Task](https://taskfile.dev) (`brew install go-task`)
- `terraform` ≥ 1.5
- `jq`, `curl`
- An LLM API key (OpenAI by default — any LiteLLM-supported provider works)

## Quick start

```sh
cp .env.example .env
# edit .env — set OPENAI_API_KEY (or your provider's key + LLM_MODEL)

task up       # start the full stack (Vault, Consul, agents, observability)
task demo     # send 10 varied tasks through the planner
```

| UI | URL |
|----|-----|
| Grafana — Agent Operations dashboard | <http://localhost:3000> |
| Jaeger | <http://localhost:16686> |
| Prometheus | <http://localhost:9090> |

## Docs

- [Architecture](docs/architecture.md) — system diagram, agent design, mesh setup, OTel Collector pipeline
- [Dashboards](docs/dashboards.md) — how to read each Grafana dashboard row and panel
- [Traces](docs/traces.md) — Jaeger span structure and filtering tips
- [Metrics reference](docs/metrics.md) — every metric, label, and PromQL query
- [Troubleshooting](docs/troubleshooting.md) — common startup and data issues

## License

MIT.
