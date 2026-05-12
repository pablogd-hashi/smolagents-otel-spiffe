"""
Executor agent — runs research / data retrieval subtasks delegated by the planner.

Exposes a single POST /run endpoint that takes a task string and returns the
agent's final answer (or a structured error).

Why this is a separate process rather than an in-process callable:

The blog post is about cross-service tracing through a service mesh. Splitting
planner and executor into their own services is what produces the
planner -> envoy -> envoy -> executor -> LLM trace shape that makes the mesh
panels meaningful. In-process delegation would collapse the trace into a single
service and we would lose half the demo.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from fastapi import FastAPI, HTTPException
from opentelemetry import metrics as otel_metrics
from pydantic import BaseModel
from smolagents import CodeAgent, LiteLLMModel
from smolagents.agents import AgentError

# Make the `agents` package importable when running from the agent's working
# directory inside the container. The Dockerfile installs the repo at /app.
sys.path.insert(0, "/app")

from agents.shared.callbacks import (  # noqa: E402
    audit_callback,
    metrics_callback,
    record_max_steps_hit,
)
from agents.shared.telemetry import init_telemetry  # noqa: E402
from agents.shared.tools import (  # noqa: E402
    call_external_api,
    run_code_snippet,
    search_knowledge_base,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("executor")

SERVICE_NAME = "executor-agent"
init_telemetry(service_name=SERVICE_NAME)

# Run-level instruments. Step-level instruments live in callbacks.py.
_meter = otel_metrics.get_meter("smolagents.runs")
_run_total = _meter.create_counter("agent_run_total", description="Total agent runs.")
_run_errors = _meter.create_counter("agent_run_errors_total", description="Failed agent runs.")
_run_duration = _meter.create_histogram(
    "agent_run_duration_seconds", unit="s", description="End-to-end run duration."
)
_run_active = _meter.create_up_down_counter(
    "agent_runs_active", description="Currently in-flight runs."
)

# A single CodeAgent per process is the right pattern for FastAPI + uvicorn:
# the agent's memory resets on every `.run()` call, so concurrent requests
# don't share state. Building a fresh CodeAgent per request would force
# reloading the model client on every call.
agent = CodeAgent(
    tools=[search_knowledge_base, call_external_api, run_code_snippet],
    model=LiteLLMModel(
        model_id=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    ),
    max_steps=int(os.environ.get("AGENT_MAX_STEPS", "8")),
    planning_interval=int(os.environ.get("AGENT_PLANNING_INTERVAL", "3")),
    additional_authorized_imports=["json", "time", "datetime", "math", "statistics"],
    step_callbacks=[audit_callback, metrics_callback],
    name="executor_agent",
    description=(
        "Executes research and data retrieval subtasks. Call with a clear, "
        "self-contained task description as a single string argument."
    ),
)


class RunRequest(BaseModel):
    task: str


app = FastAPI(title="executor-agent")


@app.get("/health")
async def health():
    """Liveness probe used by Docker Compose and Consul."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/run")
async def run_agent(req: RunRequest):
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task must be a non-empty string")

    labels = {"agent": SERVICE_NAME}
    _run_total.add(1, labels)
    _run_active.add(1, labels)
    started = time.monotonic()

    try:
        result = agent.run(req.task)
        elapsed = time.monotonic() - started

        # Detect "ran out of steps" — smolagents returns a result rather than
        # raising in this case, so the only way to spot it is to inspect the
        # last memory entry.
        last = agent.memory.steps[-1] if agent.memory.steps else None
        hit_max = (
            last is not None
            and last.__class__.__name__ == "ActionStep"
            and getattr(last, "step_number", 0) >= agent.max_steps
        )
        if hit_max:
            record_max_steps_hit(SERVICE_NAME)

        _run_duration.record(elapsed, labels)
        return {
            "status": "ok",
            "result": result,
            "duration_s": elapsed,
            "max_steps_hit": hit_max,
        }

    except AgentError as e:
        # Structured agent-level errors (planning failure, parse failure, etc.)
        # come back as 200 with status=error so the dashboards can distinguish
        # them from infrastructure failures (5xx).
        _run_errors.add(1, {**labels, "error_type": type(e).__name__})
        _run_duration.record(time.monotonic() - started, labels)
        log.exception("agent error")
        return {"status": "error", "error_type": type(e).__name__, "message": str(e)}

    except Exception as e:
        _run_errors.add(1, {**labels, "error_type": type(e).__name__})
        _run_duration.record(time.monotonic() - started, labels)
        log.exception("unexpected error")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        _run_active.add(-1, labels)
