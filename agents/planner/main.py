"""
Planner agent — decomposes user tasks and delegates to the executor.

The planner has zero tools of its own. Its only capability is to invoke the
executor as a managed agent. This forces a clean separation of concerns:
the planner reasons about *what to do*, the executor reasons about
*how to do it*. In Jaeger this shows up as a clear two-tier trace tree:

  planner.run -> [planner LLM call] -> executor.run -> [executor LLM + tools]

If you need to reach the executor over HTTP (because they live in separate
processes behind a service mesh, which is the point of this demo) instead of
calling it as an in-process managed agent, set EXECUTOR_URL and the planner
will use the HTTP-backed delegate defined below.
"""

from __future__ import annotations

import logging
import os
import sys
import time

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from pydantic import BaseModel
from smolagents import CodeAgent, LiteLLMModel, tool
from smolagents.agents import AgentError

sys.path.insert(0, "/app")

from agents.shared.callbacks import audit_callback, metrics_callback  # noqa: E402
from agents.shared.telemetry import init_telemetry  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("planner")

SERVICE_NAME = "planner-agent"
init_telemetry(service_name=SERVICE_NAME)

EXECUTOR_URL = os.environ.get("EXECUTOR_URL", "http://executor:8000")

_meter = otel_metrics.get_meter("smolagents.runs")
_run_total = _meter.create_counter("agent_run_total", description="Total agent runs.")
_run_errors = _meter.create_counter("agent_run_errors_total", description="Failed agent runs.")
_run_duration = _meter.create_histogram(
    "agent_run_duration_seconds", unit="s", description="End-to-end run duration."
)
_run_active = _meter.create_up_down_counter(
    "agent_runs_active", description="Currently in-flight runs."
)

_tracer = otel_trace.get_tracer("smolagents.planner")


@tool
def delegate_to_executor(subtask: str) -> str:
    """
    Hand a self-contained subtask to the executor agent and return its answer.

    Use this for any concrete data retrieval, calculation, or external API
    work. The planner itself should not attempt these directly. Pass a single
    clear instruction; the executor will plan its own steps.

    Args:
        subtask: A self-contained task description. Must include all the
                 context the executor needs — it has no memory of the parent
                 task. Example: "Look up the current price of BTC and ETH and
                 return them as a JSON object."

    Raises:
        ValueError: If the executor returns a structured error or is unreachable.
    """
    if not subtask or not subtask.strip():
        raise ValueError("subtask must be a non-empty string")

    # Wrap the HTTP call in a manual span so the trace shows the planner's
    # delegation as a discrete operation and not just an opaque httpx span.
    # OpenInference's smolagents instrumentor handles tool spans for us, but
    # the cross-service hop deserves its own attribute set.
    with _tracer.start_as_current_span(
        "planner.delegate", attributes={"executor.url": EXECUTOR_URL}
    ) as span:
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(f"{EXECUTOR_URL}/run", json={"task": subtask})
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as e:
            span.record_exception(e)
            raise ValueError(f"executor unreachable: {e}") from e

        if body.get("status") == "error":
            span.set_attribute("executor.error_type", body.get("error_type", "unknown"))
            raise ValueError(
                f"executor failed ({body.get('error_type')}): {body.get('message')}"
            )

        span.set_attribute("executor.duration_s", body.get("duration_s", 0))
        return str(body.get("result", ""))


agent = CodeAgent(
    tools=[delegate_to_executor],
    model=LiteLLMModel(
        model_id=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    ),
    max_steps=int(os.environ.get("AGENT_MAX_STEPS", "5")),
    planning_interval=int(os.environ.get("AGENT_PLANNING_INTERVAL", "3")),
    additional_authorized_imports=["json", "time", "datetime"],
    step_callbacks=[audit_callback, metrics_callback],
    name="planner_agent",
    description=(
        "Decomposes user tasks into concrete subtasks and delegates execution "
        "to the executor agent. Does not perform retrieval or computation itself."
    ),
)


class RunRequest(BaseModel):
    task: str


app = FastAPI(title="planner-agent")


@app.get("/health")
async def health():
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
        _run_duration.record(time.monotonic() - started, labels)
        return {"status": "ok", "result": result, "duration_s": time.monotonic() - started}

    except AgentError as e:
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
