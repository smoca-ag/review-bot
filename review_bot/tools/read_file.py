from review_bot.models import ReviewDeps
from review_bot.utils.text import paginate_text
from pydantic_ai import RunContext


def read_file(
    ctx: RunContext[ReviewDeps],
    file_path: str,
    start_line: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    Reads and returns the contents of a specific file from the repository.

    Use this tool to read the source code of a file to understand its implementation.
    The response is paginated; use `start_line` to read subsequent chunks if the file is large.

    Args:
        file_path: The path to the file to read.
        start_line: The line number to start reading from (1-indexed).
        max_lines: The maximum number of lines to return.
    """
    try:
        raw = ctx.deps.container_manager.get_file_raw(file_path)
        if raw is None:
            return f"Error: File '{file_path}' not found."
        return paginate_text(raw, start_line, max_lines, add_line_numbers=True)
    except Exception as e:
        return f"Error fetching file: {str(e)}"
