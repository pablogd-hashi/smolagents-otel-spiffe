# Metrics Reference

All metrics are emitted by the planner-agent and executor-agent processes via
the OpenTelemetry SDK, exported to the OTel Collector over OTLP/gRPC, and
forwarded to Prometheus via remote write. Grafana queries Prometheus for every
panel on the Agent Operations dashboard.

---

## Collection pipeline

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

Token-level LLM metrics are derived inside `metrics_callback` from
`ActionStep.model_output_message.raw.usage` because
`openinference-instrumentation-smolagents` 0.1.7 does not emit dedicated
LLM-kind spans — it only produces AGENT and TOOL spans.

---

## Dashboard panels

| Section | Panel | What it shows |
|---------|-------|---------------|
| Throughput & Availability | Active Agent Runs | In-flight runs right now (`agent_runs_active`) |
| | Run Rate | Runs per minute over time |
| | Error Rate % | % of runs ending in an exception |
| Run Latency | Run Duration P50/P95/P99 | End-to-end run latency percentiles |
| | Run Duration Heatmap | Distribution of run durations over time |
| LLM Call Performance | LLM Call Duration P50/P95/P99 | Step-level LLM call latency (approximated as step duration) |
| | Inter-token Latency | `step_duration / completion_tokens` — proxy for provider throughput |
| | LLM Calls per Run | Average number of LLM calls per completed run |
| | LLM Call Error Rate | Rate of LLM exceptions (rate limits, context errors, etc.) |
| | LLM Calls / sec | Overall model call throughput |
| Token Economics | Prompt Tokens / Call P50/P95 | Input token distribution per LLM call |
| | Completion Tokens / Call P50/P95 | Output token distribution per LLM call |
| | Prompt / Completion Ratio | How much of each call is prompt vs. generated output |
| | Token Throughput | Total tokens/sec (prompt + completion) |
| | Estimated Cost / Hour | Cost projection using configurable per-token prices |
| | Avg Tokens / Run | Average total tokens consumed per agent run |
| Tool Call Behaviour | Tool Call Rate by Tool | Invocation rate per tool name |
| | Tool Call Duration P95 by Tool | P95 latency broken down by tool |
| | Tool Error Rate | Error rate by tool and exception type |
| | Tool Calls per Run | Distribution of how many tool calls each run makes |
| Agent Memory & Context | Memory Messages per Step P50/P95 | Context window depth at each step — a proxy for growing prompt cost |
| | Steps per Run | Average number of reasoning steps per run, by agent |
| | Max-steps Hit Rate | Rate of runs exhausting the step budget without a final answer |
| | Final Answer Rate | Rate of runs completing cleanly with `final_answer` |
| Audit Logs | All Agent Steps | Raw structured JSON log stream from Loki, one record per step |

---

## Run-level metrics

Recorded once per `/run` request in each agent's `main.py`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `agent_run_total` | Counter | `agent` | Total `/run` requests received. Incremented at the start of every run regardless of outcome. Used for throughput panels and as the denominator in per-run averages. |
| `agent_run_errors_total` | Counter | `agent`, `error_type` | Runs that ended with an unhandled exception. `error_type` is the Python class name (e.g. `AgentError`, `APIError`). A run counted here is **not** also in `agent_max_steps_hit_total`. |
| `agent_run_duration_seconds` | Histogram | `agent` | Wall-clock time from request arrival to response. Covers all LLM calls, tool executions, and planning steps. Drives the P50/P95/P99 and heatmap panels. |
| `agent_runs_active` | UpDownCounter | `agent` | In-flight runs at this instant. Incremented on entry, decremented in `finally`. Use this to spot concurrency build-up or back-pressure. |

---

## Step-level metrics

Recorded by `metrics_callback` once per `ActionStep`. Each step is one LLM call
plus optionally one tool invocation.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `agent_step_total` | Counter | `agent`, `tool` | Steps executed. `tool` is the called tool's name, or `"none"` when the step produced a final answer directly. |
| `agent_step_duration_seconds` | Histogram | `agent`, `tool` | Wall-clock duration of a single step. Includes LLM call and tool execution. |
| `agent_step_errors_total` | Counter | `agent`, `tool`, `error_type` | Steps that raised an error. A step error does not end the run — the agent receives it as an observation and may retry. |
| `agent_final_answer_total` | Counter | `agent` | Runs that completed via `FinalAnswerStep`. A run absent from here either errored or hit the step limit. |
| `agent_max_steps_hit_total` | Counter | `agent` | Runs terminated because `max_steps` was exhausted without a `final_answer`. Signals tasks too complex for the configured budget. |

---

## Memory & context metrics

Recorded per `ActionStep`, tracking how the context window grows over a run.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `agent_memory_messages` | Histogram | `agent` | Number of memory entries in the agent's rolling context at the end of each step. Increases by one per step. Directly correlates with prompt token growth because the full conversation history is re-sent to the model on every call. |

**How to interpret:** if `histogram_quantile(0.95, rate(agent_memory_messages_bucket[5m]))` is
consistently near `max_steps`, most runs are consuming their full context budget.
Cross-reference with `llm_prompt_tokens` P95 to confirm the token cost impact.

---

## LLM metrics

Derived inside `metrics_callback` from `ActionStep.model_output_message.raw.usage`
(the raw LiteLLM `ModelResponse`). Each `ActionStep` maps to exactly one LLM call.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `llm_calls_total` | Counter | `model` | Total LLM calls across all agents. `model` is the LiteLLM model ID (e.g. `gpt-4o-mini`). |
| `llm_call_duration_seconds` | Histogram | `model` | Duration of the step containing the LLM call. **Approximation** — includes any synchronous tool work in the same step. True LLM-only latency requires server-side timing from the provider. |
| `llm_call_errors_total` | Counter | `model`, `error_type` | LLM calls that raised an exception: network error, rate limit, context-length exceeded, etc. |
| `llm_prompt_tokens` | Histogram | `model` | Prompt (input) token count per call, from the provider usage response. Grows with memory depth since the full conversation is re-sent every step. |
| `llm_completion_tokens` | Histogram | `model` | Completion (output) token count per call. Varies with response complexity. |
| `llm_inter_token_seconds` | Histogram | `model` | `step_duration / completion_tokens` — mean time per generated token. A proxy for provider-side throughput. Spikes indicate provider congestion, not agent logic issues. |

**Token Economics PromQL:**

| Panel | Query |
|-------|-------|
| Prompt tokens P50/P95 | `histogram_quantile(0.50\|0.95, sum by (le, model) (rate(llm_prompt_tokens_bucket[5m])))` |
| Completion tokens P50/P95 | `histogram_quantile(0.50\|0.95, sum by (le, model) (rate(llm_completion_tokens_bucket[5m])))` |
| Token throughput (tok/s) | `sum(rate(llm_prompt_tokens_sum[1m])) + sum(rate(llm_completion_tokens_sum[1m]))` |
| Estimated cost / hour | `(sum(rate(llm_prompt_tokens_sum[5m])) * $prompt_cost / 1000 + sum(rate(llm_completion_tokens_sum[5m])) * $completion_cost / 1000) * 3600` |
| Avg tokens / run | `(sum(rate(llm_prompt_tokens_sum[5m])) + sum(rate(llm_completion_tokens_sum[5m]))) / clamp_min(sum(rate(agent_run_total[5m])), 0.001)` |

`$prompt_cost` and `$completion_cost` default to gpt-4o-mini pricing and are
adjustable in the Grafana dashboard variables panel.

---

## Tool metrics

Recorded by `metrics_callback` per `ActionStep` where a tool was invoked.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tool_calls_total` | Counter | `tool` | Total invocations per tool name. Use to see which tools run most often and to normalise error rates. |
| `tool_call_duration_seconds` | Histogram | `tool` | Step wall-clock duration for steps that called this tool. Same approximation caveat as `llm_call_duration_seconds`. |
| `tool_call_errors_total` | Counter | `tool`, `error_type` | Tool invocations that raised an exception. The agent receives the error as a text observation and may retry with corrected arguments. |

---

## Grafana dashboard variables

| Variable | Source | Effect |
|----------|--------|--------|
| `$agent` | `label_values(agent_run_total, agent)` | Filters step, memory, and error panels to a specific agent. Defaults to both. |
| `$model` | `label_values(llm_calls_total, model)` | Filters LLM and token panels to a specific model. Useful when switching providers. |
| `$prompt_cost` | Static (default `0.00015`) | USD per 1 000 prompt tokens, used in the cost estimate panel. |
| `$completion_cost` | Static (default `0.00060`) | USD per 1 000 completion tokens. Update for your provider and model. |

---

## Audit logs (Loki)

Audit records are JSON lines emitted by `audit_callback` via Python's
`agent.audit` logger, forwarded to the OTel Collector through the SDK's
`LoggingHandler`, and stored in Loki via the Collector's OTLP log pipeline.
Every record carries `trace_id`, which Grafana's derived-fields config uses to
link a log line directly to the matching Jaeger trace.

The **All Agent Steps** panel in Grafana queries `{service_name=~".*-agent"}`.

### Record schema

| Field | Type | Present on | Description |
|-------|------|------------|-------------|
| `ts` | float | all | Unix timestamp (seconds, fractional) |
| `agent` | string | all | Agent name, e.g. `planner-agent` |
| `type` | string | all | Step class: `ActionStep`, `PlanningStep`, or `FinalAnswerStep` |
| `trace_id` | string | all | 32-hex OTel trace ID. Links to Jaeger. |
| `step_num` | int | ActionStep | Step index within the run |
| `tool` | string | ActionStep | Tool invoked, or `"none"` |
| `duration_s` | float | ActionStep | Step wall-clock time in seconds |
| `error` | string\|null | ActionStep | Error message if the step failed |
| `error_type` | string\|null | ActionStep | Python exception class name |
| `input_tokens` | int\|null | ActionStep | Prompt tokens for this LLM call |
| `output_tokens` | int\|null | ActionStep | Completion tokens for this LLM call |
| `event` | string | PlanningStep, FinalAnswerStep | `"planning_step"` or `"final_answer"` |
| `total_steps` | int | FinalAnswerStep | Total ActionSteps in the completed run |

### Useful LogQL queries

```logql
# All agent step records
{service_name=~".*-agent", scope_name="agent.audit"}

# Steps that failed
{service_name=~".*-agent", scope_name="agent.audit"} | json | error != "null"

# Follow a specific trace (replace with ID from Jaeger)
{service_name=~".*-agent", scope_name="agent.audit"} | json | trace_id = "abc123..."

# Cumulative tokens consumed by the executor over 5-minute windows
sum_over_time(
  {service_name="executor-agent", scope_name="agent.audit"}
  | json | unwrap input_tokens [5m]
)
```
