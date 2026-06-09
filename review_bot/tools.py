from pydantic_ai import RunContext, Tool

from review_bot.models import ReviewDeps
from review_bot.text_utils import is_binary, paginate_text

_MAX_FILE_LINES = 200


def fetch_file_content(
    ctx: RunContext[ReviewDeps],
    file_path: str,
    start_line: int = 1,
    max_lines: int = _MAX_FILE_LINES,
) -> str:
    """
    Fetch the contents of a specific file from the repository.

    Use this tool to read the source code of a file to understand its implementation.
    The response is paginated; use `start_line` to read subsequent chunks if the file is large.

    Args:
        file_path: The path to the file to read.
        start_line: The line number to start reading from (1-indexed).
        max_lines: The maximum number of lines to return.
    """
    try:
        raw = ctx.deps.mr_request.get_file_raw(file_path)
        if raw is None:
            return f"Error: File '{file_path}' not found."
        if isinstance(raw, bytes):
            if is_binary(raw):
                return f"Binary file '{file_path}' ({len(raw)} bytes). Cannot display binary content."
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return f"Error: File '{file_path}' appears to be non-UTF-8 encoded."
        else:
            text = raw
        return paginate_text(text, start_line, max_lines, add_line_numbers=True)
    except Exception as e:
        return f"Error fetching file: {str(e)}"


def list_files(
    ctx: RunContext[ReviewDeps],
    path: str = ".",
    start_line: int = 1,
    max_lines: int = _MAX_FILE_LINES,
) -> str:
    """
    List files and directories at a specific path in the repository.

    Use this tool to explore the project structure and find relevant files.

    Args:
        path: The directory path to list files for (defaults to root ".").
        start_line: The line number to start reading from for pagination.
        max_lines: The maximum number of lines to return.
    """
    try:
        raw = ctx.deps.mr_request.list_files(path)
        if raw.startswith("Error"):
            return raw
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error listing files: {str(e)}"


def scan_code(
    ctx: RunContext[ReviewDeps],
    pattern: str,
    path: str = ".",
    start_line: int = 1,
    max_lines: int = _MAX_FILE_LINES,
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
        raw = ctx.deps.mr_request.scan_code(pattern, path)
        if raw.startswith("Error") or raw == "No matches found.":
            return raw
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error scanning code: {str(e)}"


async def execute_command(
    ctx: RunContext[ReviewDeps],
    command: str,
    start_line: int = 1,
    max_lines: int = _MAX_FILE_LINES,
) -> str:
    """
    Execute a shell command in the repository context.

    Use this tool to run tests, linters, or other build scripts to verify code correctness.
    Commands execute in a persistent shell session, so stateful commands like `cd` persist
    across multiple invocations within the same agent.

    Args:
        command: The shell command to execute.
        start_line: The line number to start reading output from for pagination.
        max_lines: The maximum number of lines of output to return.
    """
    try:
        if ctx.deps.shell is None:
            return "Error: No shell available."
        raw = await ctx.deps.shell.execute(command)
        if raw.startswith("Error"):
            return raw
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error executing command: {str(e)}"


def vector_search(ctx: RunContext[ReviewDeps], query: str, top_k: int = 5) -> str:
    """
    Perform a semantic vector search across the codebase.

    Use this tool to find conceptually related code chunks when you don't know the exact keyword or file path.

    Args:
        query: The semantic search query describing what you're looking for.
        top_k: The number of top matching code chunks to return.
    """
    collection = ctx.deps.vector_index
    if collection is None:
        return "Vector search is not available (index not built)."
    try:
        results = collection.query(query_texts=[query], n_results=top_k)
        docs = results["documents"][0]
        if not docs:
            return "No relevant code chunks found."
        output_parts = []
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            similarity = 1.0 - dist
            output_parts.append(
                f"File: {meta['file']} (Line ~{meta['lines']}, Similarity: {similarity:.2f})\n```\n{doc}\n```"
            )
        return "\n---\n".join(output_parts)
    except Exception as e:
        return f"Error searching vector index: {str(e)}"


shared_tools = [
    Tool(fetch_file_content),
    Tool(list_files),
    Tool(scan_code),
    Tool(execute_command),
    Tool(vector_search),
]
