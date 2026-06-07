from review_bot.models import FinalReviewResult


def format_and_post_review(logger, mr_request, review_result: FinalReviewResult, post):
    status_icon = "✅" if review_result.recommend_approval else "❌"
    header_identifier = "# 🤖 AI Review"

    markdown_comment = f"{header_identifier} {status_icon}\n"
    markdown_comment += f"## Summary\n {review_result.summary}\n\n"

    if review_result.description_feedback:
        markdown_comment += (
            "## 📝 PR Description Improvements\n"
            + "\n".join(f"- {f}" for f in review_result.description_feedback)
            + "\n\n"
        )
    if review_result.security_concerns:
        markdown_comment += (
            "## 🚨 Security Concerns\n"
            + "\n".join(f"- {c}" for c in review_result.security_concerns)
            + "\n\n"
        )
    if review_result.architectural_feedback:
        markdown_comment += (
            "## 🏗️ Architecture & Design\n"
            + "\n".join(f"- {f}" for f in review_result.architectural_feedback)
            + "\n\n"
        )
    if review_result.performance_feedback:
        markdown_comment += (
            "## 🚀 Performance & Scalability\n"
            + "\n".join(f"- {f}" for f in review_result.performance_feedback)
            + "\n\n"
        )
    if review_result.testing_feedback:
        markdown_comment += (
            "## 🧪 Testing & QA\n"
            + "\n".join(f"- {f}" for f in review_result.testing_feedback)
            + "\n\n"
        )
    if review_result.actionable_feedback:
        markdown_comment += (
            "## 🛠️ Code Feedback\n"
            + "\n".join(f"- {f}" for f in review_result.actionable_feedback)
            + "\n\n"
        )
    if review_result.critical_line_comments:
        markdown_comment += (
            "## 📌 Inline Comments\n"
            + "\n".join(
                f"- {comment.file}:{comment.line} (Confidence {comment.confidence_score}): **{comment.severity.upper()} ({comment.category})**: {comment.comment}"
                for comment in review_result.critical_line_comments
            )
            + "\n\n"
        )

    for comment in review_result.critical_line_comments:
        text = f"**{comment.severity.upper()} ({comment.category})**: {comment.comment}"
        logger.info(
            f"{comment.file}:{comment.line} (Confidence {comment.confidence_score}): {text}"
        )
        if (
            post
            and comment.confidence_score >= 0.9
            and comment.severity.upper() != "MINOR"
        ):
            mr_request.post_line_review(text, comment.file, comment.line)

    logger.info("Markdown Output Generated:\n" + markdown_comment)
    if post:
        mr_request.post_review(markdown_comment)
        mr_request.publish_reviews()
        logger.info("🎉 Review posted successfully!")
    else:
        logger.info("Review generated but not posted (--post not specified).")
