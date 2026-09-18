"""Format the critic's FinalReviewResult as a GitLab markdown comment and post it."""

import os

from review_bot.models import FinalReviewResult

_CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.9"))


def _derive_severity(comment) -> str:
    if comment.risk_score >= 5 and comment.confidence_score >= 0.8:
        return "CRITICAL"
    if comment.risk_score >= 4 or (comment.risk_score >= 3 and comment.confidence_score >= 0.8):
        return "MAJOR"
    return "MINOR"


def _section(title: str, items: list[str], collapsed: bool = False) -> str:
    body = "\n".join(f"- {item}" for item in items)
    if collapsed:
        return f"<details>\n<summary>{title}</summary>\n\n{body}\n\n</details>\n\n"
    return f"## {title}\n{body}\n\n"


def format_and_post_review(logger, mr_request, review_result: FinalReviewResult, post):
    status_icon = "✅" if review_result.recommend_approval else "❌"
    header_identifier = "# 🤖 AI Review"

    markdown_comment = f"{header_identifier} {status_icon}\n"
    markdown_comment += f"## Summary\n {review_result.summary}\n\n"

    if review_result.description_feedback:
        markdown_comment += _section(
            "📝 PR Description Improvements",
            review_result.description_feedback,
            collapsed=True,
        )
    if review_result.security_concerns:
        markdown_comment += _section(
            "🚨 Security Concerns", review_result.security_concerns
        )
    if review_result.architectural_feedback:
        markdown_comment += _section(
            "🏗️ Architecture & Design",
            review_result.architectural_feedback,
            collapsed=True,
        )
    if review_result.performance_feedback:
        markdown_comment += _section(
            "🚀 Performance & Scalability",
            review_result.performance_feedback,
            collapsed=True,
        )
    if review_result.testing_feedback:
        markdown_comment += _section(
            "🧪 Testing & QA", review_result.testing_feedback, collapsed=True
        )
    if review_result.actionable_feedback:
        markdown_comment += _section("🛠️ Code Feedback", review_result.actionable_feedback)
    if review_result.critical_line_comments:
        markdown_comment += (
            "## 📌 Inline Comments\n"
            + "\n".join(
                f"- {comment.file}:{comment.line}"
                f"{'-' + str(comment.end_line) if comment.end_line else ''}"
                f" (Risk {comment.risk_score}, Confidence {comment.confidence_score})"
                f" **{_derive_severity(comment)} ({comment.category})**: {comment.comment}"
                for comment in review_result.critical_line_comments
            )
            + "\n\n"
        )

    for comment in review_result.critical_line_comments:
        severity = _derive_severity(comment)
        text = f"**{severity} ({comment.category})**: {comment.comment}"
        logger.info(
            f"{comment.file}:{comment.line} (Risk {comment.risk_score}, Confidence {comment.confidence_score}): {text}"
        )
        if (
            post
            and comment.confidence_score >= _CONFIDENCE_THRESHOLD
            and severity != "MINOR"
        ):
            mr_request.post_line_review(text, comment.file, comment.line)

    logger.info("Markdown Output Generated:\n" + markdown_comment)
    if post:
        mr_request.post_review(markdown_comment)
        logger.info("🎉 Review posted successfully!")
    else:
        logger.info("Review generated but not posted (--post not specified).")