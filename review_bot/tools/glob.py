from review_bot.models import ReviewDeps
from review_bot.utils.text import paginate_text
from pydantic_ai import RunContext


def glob(
    ctx: RunContext[ReviewDeps],
    pattern: str,
    start_line: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    Find files matching a glob pattern in the repository.

    Use this tool to search for files by name patterns (e.g. "**/*.py", "src/**/*.ts").

    Args:
        pattern: The glob pattern to match files against (e.g. "*.py", "**/*.js").
        start_line: The line number to start reading from for pagination.
        max_lines: The maximum number of lines to return.
    """
    try:
        raw = ctx.deps.container_manager.glob_files(pattern)
        if raw.startswith("Error"):
            return raw
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error globbing files: {str(e)}"
