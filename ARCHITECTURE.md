# Architecture

This document explains *why* the repo is laid out the way it is. The README covers *how* to run it.

## Components and their jobs

| Component | Job | Why this one |
|---|---|---|
| **Vault (dev mode)** | Issues the root CA, signs Consul Connect's intermediate. | The blog post's premise is zero-trust workload identity. Vault PKI is the production-grade upstream CA for Consul Connect, so even a stripped-down demo uses it rather than Consul's built-in CA. |
| **Consul + Connect** | Service catalogue + per-service Envoy sidecars + intentions. | Connect is what gives us mTLS for free between agent processes, plus default-deny intentions that let the mesh-health dashboard show "allowed vs denied" instead of trivial all-allowed traffic. |
| **Envoy sidecars** | Terminate mTLS, expose `upstream_rq_time` / `ssl_handshake` etc. on `/stats/prometheus`. | The dashboard's mesh panels would have nothing to graph without these. |
| **OpenTelemetry Collector** | Single OTLP ingress for traces, metrics, logs. Redaction, batching, tail sampling. | Centralising the pipeline means the agent processes only know "OTLP gRPC to one address." Storage choices (Jaeger vs Tempo, Prometheus vs Mimir) are a Collector config change, not an agent change. |
| **Jaeger v2** | Trace store. | OTLP-native, no jaeger-protocol shim required. |
| **Prometheus** | Metrics store, with `--web.enable-remote-write-receiver` so the Collector can push directly. | The mesh-health dashboard scrapes the sidecars directly; the agent-operations dashboard is fed by remote write. |
| **Loki** | Log store, OTLP ingest at `/otlp`. | Trace-correlation links back to Jaeger via Grafana derived fields require a structured `trace_id` field — the agents emit it in `audit_callback`. |
| **Grafana** | Provisioned datasources + provisioned dashboards. | The whole point is "clone, run, see panels." Manual import would not survive a `task clean`. |
| **smolagents planner / executor** | The agents. | Two services so the trace shape is interesting. One service would collapse the planner→executor edge into in-process calls and there would be no service-mesh story. |

## Why two agents

The planner has zero domain tools. Its only capability is `delegate_to_executor`. The executor has all the work tools: `search_knowledge_base`, `call_external_api`, `run_code_snippet`. This separation:

* makes the trace tree obvious (`planner.run` → `delegate` → `executor.run` → tool spans),
* keeps the planner's prompt small (it does not need to know how the tools work),
* matches the recommended smolagents pattern for managed agents,
* gives the mesh something real to do — the planner→executor edge is a genuine cross-service hop.

## Why every step gets two callbacks

`audit_callback` writes JSON to a logger; `metrics_callback` emits OTel metrics. They are deliberately split because:

* a noisy metric should not silently break the audit trail,
* an operator opens audit logs *during* an incident — they cannot afford for them to be missing because the metrics SDK had a bad day,
* metrics aggregate; logs do not. They serve different consumption patterns.

The `trace_id` field is the bridge: every audit record carries it, and Grafana's derived-field config on the Loki datasource turns it into a clickable Jaeger link.

## Why an in-process span processor for LLM/TOOL metrics

OpenInference's smolagents instrumentor produces LLM and TOOL spans with rich attributes (token counts, model name, tool name) but does **not** emit Prometheus-style metrics from them. There are two ways to bridge that gap:

1. **Server-side**: enable the Collector's `spanmetrics` connector, which derives histograms from spans.
2. **Client-side**: a custom `SpanProcessor` in the agent process that converts span end events into metric recordings.

We chose (2) because:

* it preserves the agent's resource attributes (`service.name`) without depending on Collector attribute promotion,
* it gives us full control over which dimensions become metric labels (model, tool, error_type) without inflating cardinality,
* it works the same way regardless of how the Collector is configured downstream — useful when the same agents run against a different observability stack.

The processor lives in `agents/shared/telemetry.py` as `_LLMSpanMetricsProcessor`. It is installed *after* the BatchSpanProcessor so that metric emission can never delay span export.

## Why tail sampling

A typical agent run spans 5–15 spans. Storing every one is wasteful when 95% of them describe identical happy-path behaviour. The Collector's `tail_sampling` processor is configured with three policies in this order:

1. **errors** — keep every trace with any ERROR-status span.
2. **slow** — keep every trace whose root span exceeded 5 s.
3. **baseline** — keep 5% of everything else.

This is the same tactic Anthropic, Honeycomb, and most OTel-native shops apply in production. The dashboards work fine off this sample because metrics are unsampled.

## Why prompt content gets hashed

`attributes/redact` in the Collector hashes the input/output content fields on every LLM span. Hashing instead of dropping preserves the ability to confirm "two calls had the same prompt" (handy for caching debugging) while never storing the actual content. Even an operator with full access to Jaeger and Loki cannot reconstruct user prompts.

This is enforced in the Collector rather than the agent because the Collector is the deployment boundary you trust — agents may be misconfigured, third-party, or compromised; the Collector is yours.

## Why dev-mode Vault and not the production setup

Production-grade Vault PKI for Consul requires:

* unsealed Vault with auto-unseal (KMS-backed),
* a long-lived Vault auth method bound to a Consul service account,
* PKI engine TTL tuning matched to the Consul Connect leaf cert lifetime,
* a Vault audit device storing every CA operation.

All of that is interesting but orthogonal to the agent observability story. The dev-mode setup here proves the wiring (Consul Connect successfully fetches its intermediate from Vault, sidecars terminate mTLS using leaves signed by that intermediate) without distracting from the main demo. The prior repo has the production version.

## What this repo is NOT

* A production smolagents deployment template. Use a real LLM gateway, real secrets management, real auth, real CA rotation.
* A SPIFFE workload-identity reference. That is the prior repo's job; here we use Consul Connect's "service identity = service name" model, which is a simpler superset.
* A complete LLM-cost dashboard. The token-cost panel uses a hardcoded per-1K-tokens rate; for real cost tracking, integrate a token-cost lookup service or a billing stream.
