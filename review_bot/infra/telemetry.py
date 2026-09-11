import logging
import os

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace.status import StatusCode
from pydantic_ai import Agent

_telemetry_setup_done = False

_tool_call_logger = logging.getLogger(__name__)

ARGUMENTS_TRUNCATE_LENGTH = 500


class ToolCallLogProcessor(SpanProcessor):
    """Log agent tool-call spans to the review logger.

    pydantic-ai's instrumentation emits one span per tool execution
    (``gen_ai.operation.name == 'execute_tool'``). This processor forwards
    those spans to the review logger as one-line INFO messages, so tool
    calls (notably ``execute_command``) are visible on stdout in addition
    to the remote OpenTelemetry export.
    """

    def on_end(self, span: ReadableSpan) -> None:
        """Emit one log line per finished tool-call span.

        Args:
            span: The span that just ended; non-tool spans are ignored.
        """
        attributes = span.attributes or {}
        if attributes.get("gen_ai.operation.name") != "execute_tool":
            return
        tool_name = attributes.get("gen_ai.tool.name", "unknown")
        arguments = str(
            attributes.get("tool_arguments")
            # instrumentation version >= 3 uses the gen_ai semantic-conventions key
            or attributes.get("gen_ai.tool.call.arguments")
            or ""
        )
        if len(arguments) > ARGUMENTS_TRUNCATE_LENGTH:
            arguments = arguments[:ARGUMENTS_TRUNCATE_LENGTH] + "..."
        duration = 0.0
        if span.start_time is not None and span.end_time is not None:
            duration = max((span.end_time - span.start_time) / 1e9, 0.0)
        status = "ERROR" if span.status.status_code == StatusCode.ERROR else "ok"
        _tool_call_logger.info(
            f"Tool call {tool_name} [{status}] ({duration:.2f}s) args={arguments}"
        )


def setup_telemetry(logger: logging.Logger | None = None) -> None:
    """Initialise OpenTelemetry tracing (idempotent).

    Tool-call logging via :class:`ToolCallLogProcessor` is always active.
    Trace export is disabled when ``DISABLE_TELEMETRY=true``. When an OTLP
    endpoint is configured via ``OTEL_EXPORTER_OTLP_ENDPOINT``, traces are
    exported to that collector; otherwise they fall back to console output
    for local debugging.

    Args:
        logger: Logger used for tool-call logging, falling back to this
            module's logger when omitted. Repeated calls update the logger.
    """
    global _telemetry_setup_done, _tool_call_logger
    if logger is not None:
        _tool_call_logger = logger
    if _telemetry_setup_done:
        return
    _telemetry_setup_done = True

    load_dotenv()

    resource = Resource(attributes={"service.name": "code-review-bot"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(ToolCallLogProcessor())

    # Export processors are skipped when telemetry is disabled entirely;
    # the tracer provider stays active so tool-call logging keeps working.
    if os.getenv("DISABLE_TELEMETRY", "").lower() == "true":
        print("Telemetry disabled via DISABLE_TELEMETRY.")
    else:
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