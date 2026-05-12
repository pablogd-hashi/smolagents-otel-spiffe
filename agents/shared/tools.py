"""
Shared tool definitions for the demo agents.

Tools simulate a HashiCorp-flavoured internal platform: a knowledge base
covering Vault, Consul, Terraform, and Nomad; an API surface for platform
health, agent telemetry, cost tracking, and secret-lease status; and a
sandboxed Python executor for quick calculations.

Latency is simulated with `time.sleep(uniform(...))` to give traces a realistic
shape for the heatmap and P95 panels.
"""

from __future__ import annotations

import json
import random
import time

from smolagents import tool

# ---------------------------------------------------------------------------
# Simulated knowledge base — HashiCorp / platform-engineering content
# ---------------------------------------------------------------------------

_KB: dict[str, list[dict]] = {
    "vault": [
        {
            "title": "Vault Dynamic Secrets: Database Engine",
            "excerpt": (
                "The database secrets engine generates short-lived credentials on demand. "
                "Configure a role with a creation statement and a TTL; Vault rotates the "
                "password automatically on lease expiry. Use `vault read database/creds/<role>` "
                "to obtain credentials at runtime without storing them in config files."
            ),
        },
        {
            "title": "Vault PKI Secrets Engine",
            "excerpt": (
                "The PKI engine acts as an intermediate CA. Issue certificates with "
                "`vault write pki/issue/<role> common_name=...`. Set `max_ttl` to a short "
                "window (e.g. 24h) for service-to-service certs to limit blast radius on "
                "compromise. Integrate with Consul Connect for automatic mTLS rotation."
            ),
        },
        {
            "title": "Vault Agent Auto-Auth",
            "excerpt": (
                "Vault Agent runs as a sidecar and authenticates to Vault on behalf of "
                "the application using an auth method such as Kubernetes, AWS IAM, or "
                "AppRole. Once authenticated it caches tokens and templates secrets into "
                "files, removing the need to hard-code Vault addresses in application code."
            ),
        },
        {
            "title": "Vault Audit Logging",
            "excerpt": (
                "Enable at least one audit device in production: `vault audit enable file "
                "file_path=/var/log/vault_audit.log`. Every request and response is logged "
                "with HMAC-hashed sensitive values. Ship logs to a SIEM and alert on "
                "repeated authentication failures or unusual lease patterns."
            ),
        },
        {
            "title": "Vault Namespaces and Multi-Tenancy",
            "excerpt": (
                "Enterprise Vault namespaces provide isolated environments with separate "
                "policies, auth methods, and secret engines. Use namespaces to segment "
                "teams or environments without running separate clusters. Namespace-scoped "
                "tokens cannot access resources in parent or sibling namespaces by default."
            ),
        },
    ],
    "consul": [
        {
            "title": "Consul Service Mesh: Connect Intentions",
            "excerpt": (
                "Intentions control which services may communicate via Consul Connect. "
                "Default-deny with explicit allow intentions gives you a strong security "
                "posture. Use `consul intention create -allow planner-agent executor-agent` "
                "to permit traffic. Intentions are enforced at the sidecar proxy level, "
                "not the application."
            ),
        },
        {
            "title": "Consul Health Checks",
            "excerpt": (
                "Register HTTP, TCP, or script checks in the service definition. Consul "
                "marks a service instance as critical when its check fails, and downstream "
                "services stop routing to it automatically. Use a check interval of 10s "
                "and a deregister_critical_service_after of 60s for fast failure detection "
                "without excessive flapping."
            ),
        },
        {
            "title": "Consul KV Store for Feature Flags",
            "excerpt": (
                "Store runtime configuration in the Consul KV store and watch for changes "
                "with `consul watch`. Applications read flags from a well-known key prefix "
                "(e.g. `config/<service>/feature/<flag>`) without restarting. Pair with "
                "Vault for sensitive values so plaintext secrets never land in the KV store."
            ),
        },
        {
            "title": "Consul Telemetry with Prometheus",
            "excerpt": (
                "Enable `telemetry { prometheus_retention_time = '60s' }` in consul.hcl. "
                "Scrape the /v1/agent/metrics?format=prometheus endpoint. Key indicators: "
                "`consul.runtime.num_goroutines`, `consul.raft.leader.lastContact`, and "
                "`consul.http.GET.v1.catalog.services` latency quantiles."
            ),
        },
        {
            "title": "Consul Envoy Sidecar Observability",
            "excerpt": (
                "Envoy sidecars injected by Consul Connect expose Prometheus metrics at "
                ":19000/stats/prometheus. Useful counters: `envoy_cluster_upstream_rq_total` "
                "(request volume), `envoy_cluster_upstream_rq_time` (latency), and "
                "`envoy_listener_ssl_handshake` (mTLS handshake rate per service pair)."
            ),
        },
    ],
    "terraform": [
        {
            "title": "Terraform State Management with Remote Backends",
            "excerpt": (
                "Store state in Terraform Cloud or an S3 backend with DynamoDB locking. "
                "Never commit state files to version control — they contain sensitive "
                "resource attributes. Use `terraform state list` and `terraform state show` "
                "to inspect live state without applying changes."
            ),
        },
        {
            "title": "Terraform Vault Provider",
            "excerpt": (
                "Use the Vault provider to read secrets at plan/apply time: "
                "`data.vault_generic_secret.db.data[\"password\"]`. Prefer short-TTL tokens "
                "scoped to the exact paths Terraform needs. Avoid storing the Vault token "
                "in plaintext; use environment variables or Vault Agent."
            ),
        },
        {
            "title": "Terraform Module Versioning",
            "excerpt": (
                "Pin module sources to a specific tag or commit hash in production: "
                "`source = \"git::https://...//modules/vpc?ref=v3.2.1\"`. Floating refs "
                "(`main`, `latest`) break reproducibility. Maintain a changelog and bump "
                "the major version for breaking interface changes."
            ),
        },
    ],
    "nomad": [
        {
            "title": "Nomad Job Scheduling and Resource Limits",
            "excerpt": (
                "Specify CPU (MHz) and memory (MB) in the `resources` block of every task. "
                "Use `memory_max` for soft limits that allow bursting when capacity is "
                "available. Enable `prevent_reschedule_on_lost` for stateful workloads that "
                "cannot safely run on a new node without manual intervention."
            ),
        },
        {
            "title": "Nomad and Consul Integration",
            "excerpt": (
                "Nomad automatically registers services in Consul when the `service` block "
                "is present in the job spec. Set `connect { sidecar_service {} }` to enable "
                "Consul Connect for the task. Nomad handles sidecar lifecycle alongside the "
                "main task without additional orchestration."
            ),
        },
    ],
    "observability": [
        {
            "title": "OpenTelemetry Collector Pipeline Design",
            "excerpt": (
                "Fan out from a single OTLP receiver to multiple backends with separate "
                "pipelines per signal type. Use the `memory_limiter` processor as the first "
                "step in every pipeline to prevent OOM crashes under load. Tail sampling in "
                "the trace pipeline lets you keep all errors and slow traces while dropping "
                "routine traffic."
            ),
        },
        {
            "title": "Distributed Tracing for Agent Workflows",
            "excerpt": (
                "Propagate the W3C `traceparent` header across service boundaries so Jaeger "
                "shows planner → executor → tool call as a single trace tree. "
                "OpenInference's smolagents instrumentor creates AGENT and TOOL spans "
                "automatically. Add a custom span around cross-service HTTP calls to capture "
                "the delegation hop explicitly."
            ),
        },
        {
            "title": "Loki Log Correlation with Traces",
            "excerpt": (
                "Include the active trace ID in every structured log line. Configure "
                "Grafana's derived fields to parse `trace_id` from Loki results and link "
                "directly to the matching Jaeger trace. This turns a slow-query alert into "
                "a one-click investigation without context switching."
            ),
        },
    ],
    "smolagents": [
        {
            "title": "smolagents CodeAgent: Tool Use Patterns",
            "excerpt": (
                "CodeAgent generates Python code to call tools rather than producing "
                "structured JSON. This allows multi-step reasoning — the agent can call "
                "search_knowledge_base, inspect the result, then conditionally call "
                "call_external_api — in a single step without re-entering the planner. "
                "Provide clear type annotations and docstrings; they become the tool spec."
            ),
        },
        {
            "title": "smolagents ManagedAgent for Multi-Agent Systems",
            "excerpt": (
                "Wrap a CodeAgent in a ManagedAgent to expose it as a tool to a parent "
                "agent. The parent sees the child as a black-box callable with a "
                "description. This produces a clean trace tree: parent span → "
                "child agent span → tool spans, enabling per-agent latency breakdown "
                "in Jaeger without coupling the two agents at the code level."
            ),
        },
        {
            "title": "smolagents Step Callbacks for Observability",
            "excerpt": (
                "Pass a list of callables to `step_callbacks` when constructing an agent. "
                "Each callback receives the completed step and the agent instance, giving "
                "access to token counts, tool results, error types, and memory depth. "
                "This is the correct hook point for emitting per-step metrics — do not "
                "instrument LiteLLM or httpx directly as that breaks across model providers."
            ),
        },
    ],
}

# Flat index: (source_id, entry) for fast lookup
_INDEX: list[tuple[str, dict]] = []
for _domain, _entries in _KB.items():
    for _i, _entry in enumerate(_entries):
        _INDEX.append((f"{_domain}_{_i:02d}", _entry))


@tool
def search_knowledge_base(query: str, top_k: int = 3) -> str:
    """
    Search the internal HashiCorp / platform-engineering knowledge base.

    Returns a JSON-encoded list of up to `top_k` document excerpts covering
    Vault, Consul, Terraform, Nomad, observability, and smolagents topics.

    Args:
        query: The search query. A concise natural-language question or keyword
               phrase (e.g. "Vault dynamic secrets", "Consul health checks",
               "Terraform state backend"). Must be non-empty.
        top_k: Number of results to return. Defaults to 3. Maximum is 10.

    Raises:
        ValueError: If `query` is empty/blank or `top_k` is out of range.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if top_k < 1 or top_k > 10:
        raise ValueError(f"top_k must be between 1 and 10 (got {top_k})")

    time.sleep(random.uniform(0.10, 0.40))

    q = query.lower()
    scored: list[tuple[float, str, dict]] = []
    for src, entry in _INDEX:
        domain = src.split("_")[0]
        text = (entry["title"] + " " + entry["excerpt"]).lower()
        # Simple keyword overlap score
        hits = sum(1 for word in q.split() if len(word) > 3 and word in text)
        domain_bonus = 0.3 if any(kw in q for kw in (domain, domain[:4])) else 0.0
        scored.append((hits + domain_bonus + random.uniform(0, 0.1), src, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [
        {
            "source": src,
            "title": entry["title"],
            "excerpt": entry["excerpt"],
            "score": round(score, 3),
        }
        for score, src, entry in scored[:top_k]
    ]
    return json.dumps(results)


@tool
def call_external_api(endpoint: str, payload: str = "") -> str:
    """
    Call a simulated platform API and return its JSON response.

    Use this for live operational data that the knowledge base does not
    provide: cluster health, agent telemetry, cost estimates, and secret
    lease status.

    Args:
        endpoint: Logical API name. Must be one of:
                  "cluster_health"  — Consul + Vault + Nomad health summary
                  "agent_telemetry" — active smolagents instances and step counts
                  "cost_estimate"   — estimated LLM token spend for the current hour
                  "lease_status"    — Vault dynamic-secret lease expiry overview
        payload: Optional JSON-encoded request body. Pass `{}` for parameterless
                 calls; pass filters as `{"service": "planner-agent"}` etc.

    Raises:
        ValueError: If `endpoint` is not one of the allowed names.
    """
    allowed = {"cluster_health", "agent_telemetry", "cost_estimate", "lease_status"}
    if endpoint not in allowed:
        raise ValueError(
            f"endpoint must be one of {sorted(allowed)} (got '{endpoint}')"
        )

    time.sleep(random.uniform(0.20, 0.90))

    if random.random() < 0.08:
        raise ValueError(f"upstream api '{endpoint}' returned 503 Service Unavailable")

    body = {
        "endpoint": endpoint,
        "received_payload": payload or None,
        "data": {
            "cluster_health": {
                "vault": {"status": "active", "sealed": False, "ha_enabled": True},
                "consul": {
                    "leader": True,
                    "peers": 1,
                    "services": {"planner-agent": "passing", "executor-agent": "passing"},
                },
                "nomad": {"nodes": 3, "jobs_running": 7, "jobs_pending": 0},
            },
            "agent_telemetry": {
                "planner_agent": {
                    "runs_total": random.randint(10, 40),
                    "runs_active": random.randint(0, 3),
                    "avg_steps": round(random.uniform(2.5, 6.5), 1),
                    "p95_duration_s": round(random.uniform(8, 25), 1),
                },
                "executor_agent": {
                    "runs_total": random.randint(15, 60),
                    "runs_active": random.randint(0, 5),
                    "avg_steps": round(random.uniform(1.5, 4.5), 1),
                    "p95_duration_s": round(random.uniform(4, 15), 1),
                },
            },
            "cost_estimate": {
                "model": "gpt-4o-mini",
                "prompt_tokens_1h": random.randint(15000, 80000),
                "completion_tokens_1h": random.randint(3000, 20000),
                "estimated_cost_usd": round(random.uniform(0.05, 0.80), 4),
                "projection_24h_usd": round(random.uniform(1.0, 18.0), 2),
            },
            "lease_status": {
                "active_leases": random.randint(20, 120),
                "expiring_1h": random.randint(0, 8),
                "expired_not_revoked": random.randint(0, 3),
                "avg_ttl_remaining_s": random.randint(600, 86400),
            },
        }[endpoint],
    }
    return json.dumps(body)


@tool
def run_code_snippet(language: str, code: str) -> str:
    """
    Execute a short Python snippet in a sandboxed environment and return stdout.

    Use this for calculations the model cannot reliably perform in its head:
    token cost estimates, TTL arithmetic, percentage breakdowns, etc.

    Args:
        language: Must be "python". No other languages are supported.
        code:     The snippet to execute. Must be under 2000 characters.
                  The imports `os` and `subprocess` are blocked at the sandbox
                  boundary for security.

    Raises:
        ValueError: If language is unsupported, code is too long, or banned
                    imports are present.
    """
    if language != "python":
        raise ValueError(f"only 'python' is supported (got '{language}')")
    if len(code) > 2000:
        raise ValueError(f"code is {len(code)} chars, limit is 2000")
    if "import os" in code or "import subprocess" in code:
        raise ValueError("banned import detected: os or subprocess")

    time.sleep(random.uniform(0.05, 0.25))

    return json.dumps(
        {
            "language": language,
            "lines_executed": len(code.splitlines()),
            "stdout": "ok\n",
            "exit_code": 0,
        }
    )
