# smolagents Observability

Production-grade observability for multi-agent AI systems built with [smolagents](https://github.com/huggingface/smolagents). This repo wires a planner / executor agent pair to a full three-signal telemetry stack — traces in Jaeger, metrics in Prometheus, structured logs in Loki — all correlated in Grafana. A Consul Connect service mesh with mTLS enforced by Vault PKI sits underneath, so every inter-agent call carries a workload identity.

## What this shows

- **Traces**: every `agent.run()` and tool invocation produces a span via `openinference-instrumentation-smolagents`. Planner → executor delegation shows up as a linked parent/child trace tree in Jaeger.
- **Metrics**: per-step counters and histograms for run throughput, latency percentiles, LLM token counts, tool call rates, and context window growth — all emitted through the OTel SDK from smolagents `step_callbacks`.
- **Audit logs**: one structured JSON record per step flows to Loki. Each record carries the trace ID, so clicking a log line in Grafana jumps directly to the Jaeger trace.
- **Service mesh**: Consul Connect with default-deny intentions and Envoy sidecars. The agents call each other over plain localhost; mTLS is enforced at the proxy layer using SPIFFE leaf certificates issued by Vault.

## Prerequisites

- Docker + Docker Compose v2
- [Task](https://taskfile.dev) (`brew install go-task`)
- `terraform` ≥ 1.5
- `jq`, `curl`
- An LLM — remote API (OpenAI, Anthropic, Groq, …) **or** a local Ollama instance

## LLM configuration

The agents use [LiteLLM](https://docs.litellm.ai) under the hood, so any provider LiteLLM supports works without code changes. Set `LLM_MODEL` and the matching API key in `.env`:

| Provider | `LLM_MODEL` | Key variable |
|----------|-------------|-------------|
| OpenAI | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-3-5-haiku-20241022` | `ANTHROPIC_API_KEY` |
| Groq | `groq/llama-3.1-70b-versatile` | `GROQ_API_KEY` |
| Ollama (local) | `ollama/qwen2.5-coder:7b` | *(none)* |

For Ollama, start it on the host before running `task up`, then set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`. Any model available via `ollama pull` works.

## Quick start

```sh
cp .env.example .env
```

Edit `.env` — at minimum set `LLM_MODEL` and the matching API key for your provider (or point `OLLAMA_BASE_URL` at a local Ollama instance).

```sh
task up       # pull images, start Vault + Consul + agents + full observability stack
task demo     # send 10 varied tasks through the planner to populate the dashboards
```

`task up` starts all containers, initialises Vault dev mode, applies Terraform (Vault PKI + Consul intentions), registers the services in Consul, and brings up the Envoy sidecars. The first run takes a minute while images are pulled.

Once the demo finishes, open the dashboards:

| UI | URL | Credentials |
|----|-----|-------------|
| Grafana — Agent Operations | <http://localhost:3000> | anonymous |
| Jaeger | <http://localhost:16686> | — |
| Prometheus | <http://localhost:9090> | — |
| Consul | <http://localhost:8500> | — |
| Vault | <http://localhost:8200> | token: `root` |

In Grafana, open the **Agent Observability** folder and select **Agent Operations**. Every panel should have data after a single `task demo` run. Click any row in the **All Agent Steps** panel at the bottom to jump to the matching trace in Jaeger.

## Docs

- [Architecture](docs/architecture.md) — system diagram, agent design, mesh setup, OTel Collector pipeline
- [Dashboards](docs/dashboards.md) — how to read each Grafana dashboard row and panel
- [Traces](docs/traces.md) — Jaeger span structure and filtering tips
- [Metrics reference](docs/metrics.md) — every metric, label, and PromQL query
- [Troubleshooting](docs/troubleshooting.md) — common startup and data issues

## License

MIT.
