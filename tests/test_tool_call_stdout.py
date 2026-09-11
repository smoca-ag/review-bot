"""Tests for tool-call span logging via ToolCallLogProcessor."""

import logging
import unittest
from unittest.mock import Mock

from opentelemetry.trace.status import StatusCode

from review_bot.infra.telemetry import (
    ARGUMENTS_TRUNCATE_LENGTH,
    ToolCallLogProcessor,
)


class _RecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_span(
    operation: str | None = "execute_tool",
    tool_name: str | None = "execute_command",
    arguments: str | None = '{"command": "rg foo src/"}',
    status_code: StatusCode = StatusCode.UNSET,
) -> Mock:
    span = Mock(spec=["attributes", "name", "start_time", "end_time", "status"])
    attributes = {}
    if operation is not None:
        attributes["gen_ai.operation.name"] = operation
    if tool_name is not None:
        attributes["gen_ai.tool.name"] = tool_name
    if arguments is not None:
        attributes["tool_arguments"] = arguments
    span.attributes = attributes
    span.name = "running tool"
    span.start_time = 1_000_000_000
    span.end_time = 2_500_000_000
    span.status = Mock(status_code=status_code)
    return span


class TestToolCallLogProcessor(unittest.TestCase):
    def setUp(self):
        self.processor = ToolCallLogProcessor()
        self.collector = _RecordCollector()
        self.logger = logging.getLogger("review_bot.infra.telemetry")
        self.logger.addHandler(self.collector)
        self.logger.setLevel(logging.INFO)

    def tearDown(self):
        self.logger.removeHandler(self.collector)
        self.logger.setLevel(logging.NOTSET)

    def test_tool_span_logged(self):
        self.processor.on_end(_make_span())
        self.assertEqual(len(self.collector.records), 1)
        message = self.collector.records[0].getMessage()
        self.assertIn("execute_command", message)
        self.assertIn("rg foo", message)
        self.assertIn("[ok]", message)
        self.assertIn("(1.50s)", message)

    def test_error_status_marked(self):
        self.processor.on_end(_make_span(status_code=StatusCode.ERROR))
        self.assertIn("[ERROR]", self.collector.records[0].getMessage())

    def test_non_tool_span_ignored(self):
        self.processor.on_end(_make_span(operation="chat"))
        self.assertEqual(self.collector.records, [])

    def test_missing_operation_attribute_ignored(self):
        self.processor.on_end(_make_span(operation=None))
        self.assertEqual(self.collector.records, [])

    def test_arguments_truncated(self):
        long_args = "x" * (ARGUMENTS_TRUNCATE_LENGTH + 100)
        self.processor.on_end(_make_span(arguments=long_args))
        message = self.collector.records[0].getMessage()
        self.assertLess(len(message), len(long_args))
        self.assertTrue(message.rstrip().endswith("..."))

    def test_missing_arguments_ok(self):
        self.processor.on_end(_make_span(arguments=None))
        self.assertEqual(len(self.collector.records), 1)
        self.assertIn("args=", self.collector.records[0].getMessage())


if __name__ == "__main__":
    unittest.main()