# Reading the Traces

Open Jaeger at <http://localhost:16686>, pick service `planner-agent`, and click any trace from the demo.

## Trace structure

A typical planner → executor delegation produces this span tree:

1. **`AGENT planner.run`** — root span for the planner's `agent.run()` call.
2. **`LLM`** — the planner's first model call. Attributes: `llm.model_name`, `llm.token_count.prompt`, `llm.token_count.completion`.
3. **`TOOL delegate_to_executor`** — the planner deciding to delegate.
4. **`planner.delegate`** — the manual span around the HTTP call to the executor (carries `executor.url`, `executor.duration_s`).
5. **`AGENT executor.run`** — the executor's root span (linked to the planner's via parent context).
6. **A series of `LLM` and `TOOL` spans** under the executor — the actual work.

## Instrumentation source

Spans are produced by `openinference-instrumentation-smolagents` (`SmolagentsInstrumentor`), which creates AGENT-kind and TOOL-kind spans for every `agent.run()` and tool invocation. LLM-kind spans are **not** produced by this version of the instrumentor; token counts are instead derived from `ActionStep.model_output_message.raw.usage` inside `metrics_callback` and emitted as histograms.

## Content redaction

Spans with `attributes/redact` applied show prompt and completion content as a stable SHA-256 hash, not raw text. This is enforced in the OTel Collector pipeline, not in the agent code, so even a misconfigured agent cannot leak content into Jaeger.

## Linking traces to logs

Every audit log record carries a `trace_id` field (32-hex OTel trace ID). Grafana's Loki datasource is configured with a derived field that parses this value and renders it as a link to the matching Jaeger trace. Click any row in the **All Agent Steps** panel to open the trace.

## Filtering tips

- **By service**: filter to `planner-agent` for delegation behaviour, `executor-agent` for tool-level timing.
- **By duration**: use the min/max duration sliders to find the outlier runs visible in the P95/P99 panels.
- **By error**: set Tags `error=true` to find runs that hit an exception — the span will contain the `exception.message` attribute.
- **By trace ID**: paste a trace ID from a Loki audit log row directly into the search box.
