from review_bot.models import ReviewDeps
from review_bot.utils.text import paginate_text
from pydantic_ai import RunContext


def list_files(
    ctx: RunContext[ReviewDeps],
    path: str = ".",
    recursive: bool = False,
    start_line: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    List files and directories at a specific path in the repository.

    Use this tool to explore the project structure and find relevant files.

    Args:
        path: The directory path to list files for (defaults to root ".").
        recursive: If True, list all files recursively under the path.
        start_line: The line number to start reading from for pagination.
        max_lines: The maximum number of lines to return.
    """
    try:
        raw = ctx.deps.container_manager.list_files(path, recursive=recursive)
        if raw.startswith("Error"):
            return raw
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error listing files: {str(e)}"