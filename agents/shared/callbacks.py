"""
Step callbacks attached to every CodeAgent in this repo.

Two callbacks, two distinct concerns:

* `audit_callback` writes an immutable structured JSON record per step. These
  records flow to Loki via the OTel Collector and are what an operator opens
  during an incident to see *what the agent did*, in order, with timing.

* `metrics_callback` emits Prometheus-compatible counters and histograms via
  the OTel metrics SDK. These power the throughput, latency and error-rate
  panels on the agent-operations dashboard.

Keeping them separate is deliberate. Audit logs are written even when the
metrics SDK is misconfigured, and a noisy metric does not pollute the audit
trail. The two pipelines fail independently.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from smolagents.memory import ActionStep, FinalAnswerStep, PlanningStep

# Dedicated logger so the deployment can route audit records to its own
# handler/file without entangling them with general application logs.
audit_logger = logging.getLogger("agent.audit")

# Module-scoped meter and instruments. Created lazily on first use to avoid
# touching the MeterProvider before `init_telemetry()` runs.
_meter = None
_step_count = None
_step_duration = None
_step_errors = None
_memory_messages = None
_planning_steps = None
_max_steps_hit = None
_final_answer = None
# LLM metrics — sourced from ActionStep.input_token_count / output_token_count
# because openinference-instrumentation-smolagents does not emit LLM-kind spans.
_llm_calls = None
_llm_duration = None
_llm_prompt_tokens = None
_llm_completion_tokens = None
_llm_inter_token = None
_llm_errors = None


def _ensure_instruments() -> None:
    """Create instruments on first call. Subsequent calls reuse the cache."""
    global _meter, _step_count, _step_duration, _step_errors
    global _memory_messages, _planning_steps, _max_steps_hit, _final_answer
    global _llm_calls, _llm_duration, _llm_prompt_tokens, _llm_completion_tokens
    global _llm_inter_token, _llm_errors

    if _meter is not None:
        return

    _meter = otel_metrics.get_meter("smolagents.callbacks")

    _step_count = _meter.create_counter(
        "agent_step_total",
        description="Total agent steps executed, labelled by agent and tool.",
    )
    _step_duration = _meter.create_histogram(
        "agent_step_duration_seconds",
        unit="s",
        description="Wall-clock duration of a single agent step.",
    )
    _step_errors = _meter.create_counter(
        "agent_step_errors_total",
        description="Step failures, labelled by agent, tool and error type.",
    )
    _memory_messages = _meter.create_histogram(
        "agent_memory_messages",
        description="Number of messages in agent memory at this step.",
    )
    _planning_steps = _meter.create_counter(
        "agent_planning_steps_total",
        description="Number of PlanningStep events triggered.",
    )
    _max_steps_hit = _meter.create_counter(
        "agent_max_steps_hit_total",
        description="Runs that terminated by hitting max_steps without a final answer.",
    )
    _final_answer = _meter.create_counter(
        "agent_final_answer_total",
        description="Runs that completed with a final_answer call.",
    )
    # LLM metrics derived from ActionStep token counts. Each ActionStep
    # corresponds to exactly one LLM call, so step.duration approximates
    # LLM call duration (tool execution time is subtracted where possible).
    _llm_calls = _meter.create_counter(
        "llm_calls_total",
        description="Total LLM calls (one per agent step).",
    )
    _llm_duration = _meter.create_histogram(
        "llm_call_duration_seconds",
        unit="s",
        description="LLM call wall-clock duration (approximated as step duration).",
    )
    _llm_prompt_tokens = _meter.create_histogram(
        "llm_prompt_tokens",
        description="Prompt token count per LLM call.",
    )
    _llm_completion_tokens = _meter.create_histogram(
        "llm_completion_tokens",
        description="Completion token count per LLM call.",
    )
    _llm_inter_token = _meter.create_histogram(
        "llm_inter_token_seconds",
        unit="s",
        description="Mean per-token generation latency (duration / completion_tokens).",
    )
    _llm_errors = _meter.create_counter(
        "llm_call_errors_total",
        description="LLM call errors, labelled by error type.",
    )


def _tool_name(step: ActionStep) -> str:
    """Best-effort tool name extraction. ActionStep without a tool returns 'none'."""
    if step.tool_calls:
        return step.tool_calls[0].name
    return "none"


def _token_counts(step: ActionStep) -> tuple[int | None, int | None]:
    """
    Extract (prompt_tokens, completion_tokens) from the step's raw LLM response.

    smolagents 1.14.0 stores the raw LiteLLM ModelResponse on
    step.model_output_message.raw. The usage object on that response has
    prompt_tokens and completion_tokens. Earlier attributes like
    input_token_count / output_token_count no longer exist on ActionStep.
    """
    try:
        usage = step.model_output_message.raw.usage
        return int(usage.prompt_tokens), int(usage.completion_tokens)
    except Exception:
        return None, None


def _current_trace_id() -> str | None:
    """Return the current trace ID as hex, or None outside an active span."""
    span = otel_trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def audit_callback(step: Any, agent: Any) -> None:
    """
    Append-only structured record per step.

    The `trace_id` field is what links a Loki log line back to the Jaeger trace
    in Grafana's derived-fields config. Every record carries it.
    """
    record: dict[str, Any] = {
        "ts": time.time(),
        "agent": getattr(agent, "name", "unknown").replace("_", "-"),
        "type": type(step).__name__,
        "trace_id": _current_trace_id(),
    }

    if isinstance(step, ActionStep):
        record.update(
            {
                "step_num": step.step_number,
                "tool": _tool_name(step),
                "duration_s": step.duration,
                "error": str(step.error) if step.error else None,
                "error_type": type(step.error).__name__ if step.error else None,
                "input_tokens": _token_counts(step)[0],
                "output_tokens": _token_counts(step)[1],
            }
        )
    elif isinstance(step, PlanningStep):
        record["event"] = "planning_step"
    elif isinstance(step, FinalAnswerStep):
        record["event"] = "final_answer"
        record["total_steps"] = sum(
            1 for s in agent.memory.steps if isinstance(s, ActionStep)
        )

    audit_logger.info(json.dumps(record))


def metrics_callback(step: Any, agent: Any) -> None:
    """Emit per-step counters and histograms."""
    _ensure_instruments()
    # Normalise to dashes so this label matches the service-name format used
    # by agent_run_total (SERVICE_NAME = "planner-agent"), which drives the
    # $agent Grafana variable. agent.name uses underscores ("planner_agent").
    agent_name = getattr(agent, "name", "unknown").replace("_", "-")

    if isinstance(step, ActionStep):
        labels = {"agent": agent_name, "tool": _tool_name(step)}
        _step_count.add(1, labels)

        if step.duration is not None:
            _step_duration.record(step.duration, labels)

        if step.error is not None:
            err_labels = dict(labels)
            err_labels["error_type"] = type(step.error).__name__
            _step_errors.add(1, err_labels)

        # Memory growth — count of messages at the *end* of this step.
        try:
            msgs = len(agent.memory.steps)
            _memory_messages.record(msgs, {"agent": agent_name})
        except Exception:
            pass

        # LLM metrics — each ActionStep is exactly one LLM call.
        # openinference-instrumentation-smolagents does not emit LLM-kind spans,
        # so we derive these metrics from the token counts smolagents records on
        # the step after the model returns.
        llm_labels = {"model": getattr(getattr(agent, "model", None), "model_id", "unknown")}
        _llm_calls.add(1, llm_labels)
        if step.duration is not None:
            _llm_duration.record(step.duration, llm_labels)
        prompt_tokens, completion_tokens = _token_counts(step)
        if prompt_tokens:
            _llm_prompt_tokens.record(prompt_tokens, llm_labels)
        if completion_tokens:
            _llm_completion_tokens.record(completion_tokens, llm_labels)
            if step.duration is not None:
                _llm_inter_token.record(step.duration / completion_tokens, llm_labels)
        if step.error is not None:
            _llm_errors.add(1, {**llm_labels, "error_type": type(step.error).__name__})

    elif isinstance(step, PlanningStep):
        _planning_steps.add(1, {"agent": agent_name})

    elif isinstance(step, FinalAnswerStep):
        _final_answer.add(1, {"agent": agent_name})


def record_max_steps_hit(agent_name: str) -> None:
    """Called from the API layer when an agent terminates by exhausting steps."""
    _ensure_instruments()
    _max_steps_hit.add(1, {"agent": agent_name})
