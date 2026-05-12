"""
OpenTelemetry initialisation for smolagents processes.

Each agent process calls `init_telemetry()` exactly once at startup. The
function configures a TracerProvider, MeterProvider, and LoggerProvider, wires
all three to the OTel Collector over OTLP/gRPC, and instruments the smolagents
library so every AGENT / TOOL operation emits a span automatically.

Audit logs (agent.audit logger) are forwarded to the LoggerProvider so they
flow through the Collector to Loki. This lets Grafana correlate log lines with
traces via the trace_id field that every audit record carries.

Why this lives in shared/ rather than each agent's main.py:

Every agent process must emit spans, metrics, and logs under the same resource
attributes (service.name, deployment.environment) so the dashboards can group
and filter across both agents without per-service configuration.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from openinference.instrumentation.smolagents import SmolagentsInstrumentor

_initialised = False


def init_telemetry(service_name: str, service_version: str = "0.1.0") -> None:
    """
    Configure OTel exporters and instrument smolagents.

    Idempotent: safe to call more than once (subsequent calls are no-ops).

    Args:
        service_name: The OTel `service.name` resource attribute. Use a stable
                      name like "planner-agent" — it shows up as the service
                      filter in Jaeger and as a label in Prometheus.
        service_version: The `service.version` attribute. Bump when you ship a
                         meaningful change to the agent's prompt or tool set.
    """
    global _initialised
    if _initialised:
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": os.environ.get("DEPLOY_ENV", "local"),
        }
    )

    # --- Traces -----------------------------------------------------------
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ----------------------------------------------------------
    # 10s export interval: fast enough for dashboards to feel live, slow enough
    # to keep cardinality cost reasonable at the Collector's remote-write fan-out.
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True),
        export_interval_millis=10_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # --- Logs -------------------------------------------------------------
    # Route the audit logger (and any other Python logger) to the OTel
    # Collector so records land in Loki. The audit records already carry
    # trace_id, which Grafana's derived-fields config uses to link a Loki
    # log line directly to its Jaeger trace.
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    set_logger_provider(logger_provider)

    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    # Attach to the audit logger specifically so every structured step record
    # is forwarded. Also attach to the root logger so application warnings
    # and errors appear in Loki alongside the audit trail.
    logging.getLogger("agent.audit").addHandler(otel_handler)
    logging.getLogger().addHandler(otel_handler)

    # --- smolagents instrumentation --------------------------------------
    SmolagentsInstrumentor().instrument(tracer_provider=tracer_provider)

    logging.getLogger(__name__).info(
        "telemetry initialised", extra={"service": service_name, "endpoint": endpoint}
    )
    _initialised = True


def get_tracer(name: Optional[str] = None):
    """Convenience accessor for the global tracer."""
    return trace.get_tracer(name or "smolagents.agent")


def get_meter(name: Optional[str] = None):
    """Convenience accessor for the global meter."""
    return metrics.get_meter(name or "smolagents.agent")
