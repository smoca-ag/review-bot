"""Tests for the top-level review comment formatter."""

import unittest
from typing import Any

from review_bot.models import FinalReviewResult
from review_bot.orchestration.formatter import format_and_post_review


def _make_result(**overrides: Any) -> FinalReviewResult:
    defaults: dict[str, Any] = dict(
        summary="Two critical issues found.",
        has_purpose=True,
        has_test_plan=False,
        description_feedback=["Missing rollback plan."],
        security_concerns=["SQL injection risk in login."],
        architectural_feedback=["Service layer leaks into views."],
        performance_feedback=["N+1 query in list view."],
        testing_feedback=["No tests for the auth flow."],
        actionable_feedback=["Fix off-by-one in the retry loop."],
        recommend_approval=False,
        critical_line_comments=[],
    )
    defaults.update(overrides)
    return FinalReviewResult(**defaults)


class _CaptureLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)

    def get_markdown(self) -> str:
        for message in self.messages:
            if message.startswith("Markdown Output Generated:\n"):
                return message.removeprefix("Markdown Output Generated:\n")
        raise AssertionError("markdown output was not logged")


class _DummyRequest:
    def post_review(self, text):
        raise AssertionError("must not post when post=False")

    def post_line_review(self, *args):
        raise AssertionError("must not post when post=False")


class TestFormatAndPostReview(unittest.TestCase):
    def _format(self, result: FinalReviewResult) -> str:
        logger = _CaptureLogger()
        format_and_post_review(logger, _DummyRequest(), result, post=False)
        return logger.get_markdown()

    def test_secondary_sections_collapsed(self):
        markdown = self._format(_make_result())
        for title in (
            "📝 PR Description Improvements",
            "🏗️ Architecture & Design",
            "🚀 Performance & Scalability",
            "🧪 Testing & QA",
        ):
            self.assertIn(f"<summary>{title}</summary>", markdown)
            self.assertNotIn(f"## {title}\n", markdown)

    def test_primary_sections_expanded(self):
        markdown = self._format(_make_result())
        for title in ("Summary", "🚨 Security Concerns", "🛠️ Code Feedback"):
            self.assertIn(f"## {title}\n", markdown)
        self.assertNotIn("<summary>🚨 Security Concerns</summary>", markdown)
        self.assertNotIn("<summary>🛠️ Code Feedback</summary>", markdown)

    def test_collapsed_sections_keep_items(self):
        markdown = self._format(_make_result())
        self.assertIn("- N+1 query in list view.", markdown)
        self.assertIn("</details>", markdown)

    def test_empty_sections_omitted(self):
        markdown = self._format(
            _make_result(
                description_feedback=[],
                architectural_feedback=[],
                performance_feedback=[],
                testing_feedback=[],
            )
        )
        self.assertNotIn("<details>", markdown)


if __name__ == "__main__":
    unittest.main()
