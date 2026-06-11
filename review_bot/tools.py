import os
from datetime import datetime, timezone

from pydantic_ai import RunContext, Tool

from review_bot.models import BotImprovementSuggestion, ReviewDeps
from review_bot.text_utils import is_binary, paginate_text


def fetch_file_content(
    ctx: RunContext[ReviewDeps],
    file_path: str,
    start_line: int = 1,
    max_lines: int | None = None,
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
    max_lines: int | None = None,
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
    max_lines: int | None = None,
) -> str:
    """
    Execute a shell command in the repository context.

    Use this tool inside a container to run tests,
    linters, or other build scripts to verify code correctness.
    The source code is checked out to /workspace.

    You are strongly encouraged to use this tool to verify your findings.
    For example: `pytest tests/`, `mypy src/`, `npm run test`, `node -e "..."`, `python -c "..."`.

    Args:
        command: The shell command to execute.
        start_line: The line number to start reading output from for pagination.
        max_lines: The maximum number of lines of output to return.
    """
    try:
        raw = ctx.deps.mr_request.execute_command(command)
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


def suggest_bot_improvement(
    ctx: RunContext[ReviewDeps],
    category: str,
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
        # Determine the log file path
        log_dir = os.path.expanduser("~/.review-bot")
        log_file = os.path.join(log_dir, "improvements.log")

        # Create directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)

        # Create the suggestion record
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

        # Append as JSON line
        with open(log_file, "a") as f:
            f.write(entry.model_dump_json() + "\n")

        return f"Suggestion recorded: [{category}] {suggestion}"
    except Exception as e:
        return f"Error recording suggestion: {str(e)}"


shared_tools = [
    Tool(fetch_file_content),
    Tool(list_files),
    Tool(scan_code),
    Tool(execute_command),
    Tool(vector_search),
    Tool(suggest_bot_improvement),
]
