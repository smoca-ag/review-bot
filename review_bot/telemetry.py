import os

import dotenv
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from pydantic_ai import Agent

_telemetry_setup_done = False


def setup_telemetry():
    """Initialise OpenTelemetry tracing (idempotent).

    Telemetry is disabled entirely when ``DISABLE_TELEMETRY=true``.
    When an OTLP endpoint is configured via ``OTEL_EXPORTER_OTLP_ENDPOINT``,
    traces are exported to that collector; otherwise they fall back to
    console output for local debugging.
    """
    global _telemetry_setup_done
    if _telemetry_setup_done:
        return
    _telemetry_setup_done = True

    dotenv.load_dotenv()

    resource = Resource(attributes={"service.name": "code-review-bot"})
    provider = TracerProvider(resource=resource)

    # Allow telemetry to be disabled entirely
    if os.getenv("DISABLE_TELEMETRY", "").lower() == "true":
        print("Telemetry disabled via DISABLE_TELEMETRY.")
        return

    # Check for the STANDARD OpenTelemetry environment variable
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        print(f"Standard OTLP endpoint detected: {otlp_endpoint}")

        # The SDK automatically reads OTEL_EXPORTER_OTLP_ENDPOINT and applies it.
        otlp_exporter = OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    else:
        print("No OTLP endpoint defined. Falling back to Console Output.")
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    # Instrument pydantic_ai agents – safe to call multiple times (no-op after first).
    Agent.instrument_all()
