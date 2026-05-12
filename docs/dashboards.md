# Reading the Dashboards

Open Grafana at <http://localhost:3000> (anonymous admin). Dashboards are in the *Agent Observability* folder.

## Agent Operations

The headline dashboard. Each row answers a different operational question.

| Row | Question |
|-----|----------|
| Throughput & Availability | Are the agents alive and serving traffic? |
| Run Latency | How long does end-to-end agent reasoning take? |
| LLM Call Performance | Where is time *actually* going inside a run? |
| Token Economics | What is this costing, and is it growing? |
| Tool Call Behaviour | Which tools are slow / breaking / overused? |
| Agent Memory & Context | Is context growing unbounded? Are agents finishing or stalling? |
| Audit Logs | What did the agent do, exactly? |

### Key panels

**Memory messages per step** — the panel most agent dashboards omit. A growing slope here is the direct cause of a growing prompt-token panel: verbose tool responses accumulate in memory, and the model re-reads the full conversation history on every step. Cross-reference with the Prompt Tokens P95 panel to see the token cost of memory growth.

**Max-steps Hit Rate** — if this is non-zero, some tasks are too complex for the configured `max_steps` budget. Increase `max_steps` on the executor, simplify the task, or add a planning step that breaks the task down further.

**Final Answer Rate** — the complement of error rate + max-steps rate. A healthy run ends here.

**Estimated Cost / Hour** — driven by the `$prompt_cost` and `$completion_cost` dashboard variables (default: gpt-4o-mini pricing). Update these in the Variables panel for your actual provider and model.

### Dashboard variables

| Variable | Effect |
|----------|--------|
| `$agent` | Filter step, memory, and error panels to one agent |
| `$model` | Filter LLM and token panels to one model |
| `$prompt_cost` | USD per 1 000 prompt tokens for the cost panel |
| `$completion_cost` | USD per 1 000 completion tokens for the cost panel |

### Audit log panel

The **All Agent Steps** panel queries Loki for `{service_name=~".*-agent", scope_name="agent.audit"}` and displays raw JSON records. Each record is one `ActionStep`, `PlanningStep`, or `FinalAnswerStep`. Clicking a row opens the matching Jaeger trace via the `trace_id` derived field.

See [metrics.md](metrics.md) for the full audit record schema.

## Consul Mesh Health

A smaller dashboard covering the Envoy sidecar layer:

- Connection counts per service pair
- mTLS handshake rate
- P99 upstream latency per service
- Intention allow/deny outcomes

Data comes from Prometheus scraping the Envoy admin endpoint (`/metrics`) on port 19001 of each agent container (the sidecar shares the agent's network namespace, so `planner:19001` and `executor:19001` reach the respective Envoy processes).
