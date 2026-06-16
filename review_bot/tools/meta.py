import os
from datetime import datetime, timezone
from typing import Literal

from review_bot.models import BotImprovementSuggestion, ReviewDeps
from pydantic_ai import RunContext


def suggest_bot_improvement(
    ctx: RunContext[ReviewDeps],
    category: Literal[
        "missing_tool",
        "missing_dependency",
        "missing_capability",
        "prompt_improvement",
        "other",
    ],
    description: str,
    suggestion: str,
    context: str,
) -> str:
    """
    Suggest an improvement to the review bot itself.

    Use this tool when you encounter a limitation that prevents you from
    verifying a finding or performing your review effectively. This helps
    the bot learn from its own limitations and improve over time.

    Examples:
    - Missing a tool: "I suspected a type error but could not verify it without mypy"
    - Missing dependency: "I could not run the test suite because pytest is not installed"
    - Missing capability: "I cannot verify database queries without a postgres client"
    - Prompt improvement: "The prompt should instruct agents to check for X"

    Args:
        category: One of: missing_tool, missing_dependency, missing_capability, prompt_improvement, other.
        description: What limitation was encountered during the review.
        suggestion: Concrete suggestion to improve the bot (e.g., 'Install mypy in the container').
        context: Context where the limitation was encountered (e.g., file path, code snippet, scenario).
    """
    try:
        log_dir = os.path.expanduser("~/.review-bot")
        log_file = os.path.join(log_dir, "improvements.log")

        os.makedirs(log_dir, exist_ok=True)

        entry = BotImprovementSuggestion(
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_name=ctx.deps.mr_request.__class__.__name__
            if hasattr(ctx.deps, "mr_request")
            else "unknown",
            category=category,
            description=description,
            suggestion=suggestion,
            context=context,
        )

        with open(log_file, "a") as f:
            f.write(entry.model_dump_json() + "\n")

        return f"Suggestion recorded: [{category}] {suggestion}"
    except Exception as e:
        return f"Error recording suggestion: {str(e)}"