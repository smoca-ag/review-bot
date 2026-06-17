from review_bot.models import ReviewDeps
from review_bot.utils.text import paginate_text
from pydantic_ai import RunContext


def search_code(
    ctx: RunContext[ReviewDeps],
    pattern: str,
    path: str = ".",
    start_line: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    Search for a text pattern in the repository code.

    Use this tool to find references to functions, classes, or specific strings across the codebase.

    Args:
        pattern: The text pattern or regex to search for.
        path: The directory path to constrain the search (defaults to root ".").
        start_line: The line number to start reading from for pagination.
        max_lines: The maximum number of lines to return.
    """
    try:
        raw = ctx.deps.container_manager.scan_code(pattern, path)
        if raw.startswith("Error") or raw == "No matches found.":
            return raw
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error scanning code: {str(e)}"