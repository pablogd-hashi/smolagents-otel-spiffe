# Architecture

## System diagram

```
            ┌─────────────────────────────────────────────────────────┐
            │                       Vault (PKI)                        │
            │   root CA  →  Consul Connect intermediate signing CA    │
            └─────────────────────┬───────────────────────────────────┘
                                  │ (Terraform-applied)
                                  ▼
   ┌──────────┐   mTLS    ┌───────────────┐   mTLS    ┌──────────┐
   │ planner  │◄─────────►│   Envoy SC    │◄─────────►│  Envoy   │
   │  agent   │           │ planner side  │           │ executor │
   │ (FastAPI)│           └───────────────┘           │ sidecar  │
   └────┬─────┘                                       └────┬─────┘
        │                                                  │
        │   OTLP (traces / metrics / logs)                 │
        ▼                                                  ▼
   ┌─────────────────────────────────────────────────────────┐
   │             OpenTelemetry Collector                       │
   │   (memory_limiter → batch → redact → tail-sampling)       │
   └────────────┬───────────────────┬──────────────┬───────────┘
                ▼                   ▼              ▼
          ┌──────────┐        ┌──────────┐   ┌──────────┐
          │  Jaeger  │        │ Prometheus│   │   Loki   │
          └────┬─────┘        └─────┬────┘   └────┬─────┘
               └────────────┬───────┴──────────┬──┘
                            ▼                  ▼
                       ┌──────────────────────────┐
                       │         Grafana          │
                       │ • Agent Operations       │
                       │ • Consul Mesh Health     │
                       └──────────────────────────┘
```

## Signal flow

Every edge between agents passes through Consul-managed Envoy sidecars with mTLS, leaf certificates issued by Consul Connect, with Vault as the upstream CA. Every agent process emits OTLP to the Collector, which fans out to three storage backends.

### Telemetry pipeline

```
smolagents step_callbacks
        │
        ├─ metrics_callback  ──► OTLPMetricExporter ──► OTel Collector ──► Prometheus remote-write
        │                          (10 s interval)
        └─ audit_callback    ──► OTLPLogExporter    ──► OTel Collector ──► Loki OTLP endpoint
                                   (batched)

SmolagentsInstrumentor
        └─ AGENT / TOOL spans ──► OTLPSpanExporter ──► OTel Collector ──► Jaeger
```

### Repo layout

```
.
├── agents/
│   ├── shared/         # telemetry init, callbacks, tools — used by both agents
│   ├── planner/        # FastAPI + CodeAgent + delegate_to_executor tool
│   └── executor/       # FastAPI + CodeAgent + research/api/code tools
├── terraform/          # Vault PKI + Consul Connect intentions
├── consul/             # Consul agent config + generated Envoy bootstraps
├── otel-collector/     # OTLP receiver, batching, redaction, tail-sampling
├── prometheus/         # remote-write receiver + Envoy sidecar scrape
├── loki/               # single-binary, OTLP HTTP receiver
├── grafana/
│   ├── provisioning/   # auto-loaded datasources + dashboards loader
│   └── dashboards/     # agent-operations.json (primary), mesh-health.json
└── bin/                # vault setup, service registration, demo traffic
```

## Agent design

**Planner** (`planner-agent`) is a `CodeAgent` with `planning_interval=3`. It holds a single tool: `delegate_to_executor`, which wraps an HTTP call to the executor's `/run` endpoint. Every delegation crosses the Consul Connect mesh, meaning the HTTP call carries a Consul-issued leaf certificate and passes through the Envoy sidecar.

**Executor** (`executor-agent`) is a `CodeAgent` with `planning_interval=2`. It holds three tools: `search_knowledge_base`, `call_external_api`, and `run_code_snippet`. Tool implementations live in `agents/shared/tools.py`; they simulate a HashiCorp internal platform with realistic latency profiles.

Both agents call `init_telemetry()` at startup, which configures a shared TracerProvider, MeterProvider, and LoggerProvider all exporting via OTLP gRPC to the Collector. `SmolagentsInstrumentor` is applied once per process to auto-instrument every AGENT and TOOL span.

## Mesh and identity

Vault runs in dev mode and acts as a root CA. Terraform applies a PKI secrets engine and Consul Connect configuration, turning Consul into an mTLS-capable service mesh with Vault as the upstream signing authority.

Each agent container runs without a sidecar by default. `task up` generates Envoy bootstrap configs (`bin/register-services.sh`) and starts the sidecar containers (`planner-sidecar`, `executor-sidecar`) which share the agent's network namespace via `network_mode: service:<agent>`. Inter-agent HTTP traffic flows through the sidecars; intra-container traffic (agent → OTel Collector) bypasses the mesh.

Consul Connect intentions are set to default-deny with an explicit allow for `planner-agent → executor-agent`. Envoy enforces intentions at the proxy level — the application code does not need to check them.

## OTel Collector pipeline

The Collector config (`otel-collector/config.yaml`) runs three pipelines:

| Signal | Processors | Exporter |
|--------|------------|---------|
| Traces | `memory_limiter` → `batch` → `attributes/redact` → `tail_sampling` | `jaeger` |
| Metrics | `memory_limiter` → `batch` | `prometheusremotewrite` |
| Logs | `memory_limiter` → `batch` | `otlphttp` (Loki) |

`attributes/redact` hashes prompt and completion content in span attributes so raw LLM text never reaches Jaeger. Tail sampling keeps 100% of error traces and 5% of baseline traffic; adjust `decision_wait` and policies in `otel-collector/config.yaml` for your traffic volume.
