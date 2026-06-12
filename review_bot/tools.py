import os
from datetime import datetime, timezone

from pydantic_ai import RunContext, Tool

from review_bot.models import BotImprovementSuggestion, ReviewDeps
from review_bot.text_utils import (
    DiffHunk,
    extract_hunks,
    inject_line_numbers,
    paginate_text,
    parse_diff_into_files,
)


def _format_dep_graph(graph) -> str:
    lines = [f"Modules: {len(graph.modules)}"]
    total_imports = sum(len(m.imports) for m in graph.modules.values())
    total_deps = sum(len(v) for v in graph.dependents.values())
    lines.append(f"Total imports: {total_imports}, Total dependent edges: {total_deps}")
    for path in sorted(graph.modules):
        m = graph.modules[path]
        deps = graph.dependents.get(path, set())
        lines.append(f"  {path} ({m.language}) — {len(m.imports)} imports, {len(deps)} dependents")
    return "\n".join(lines)


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
        return paginate_text(raw, start_line, max_lines, add_line_numbers=True)
    except Exception as e:
        return f"Error fetching file: {str(e)}"


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
        raw = ctx.deps.mr_request.list_files(path, recursive=recursive)
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


def diff_context(
    ctx: RunContext[ReviewDeps],
    file_path: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    context_lines: int = 3,
    start_page: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    View focused sections of the code diff with configurable context.

    Use this tool to drill into specific files or line ranges in the diff,
    especially when the full diff in the prompt was truncated. You can narrow
    to a single file, a line range, and control how many surrounding unchanged
    lines are shown around each change.

    Args:
        file_path: Filter to a single file path (e.g. "src/auth.py"). None returns all files.
        start_line: New-file line number to start from (1-indexed). None starts from the beginning.
        end_line: New-file line number to end at (1-indexed, inclusive). None goes to the end.
        context_lines: Number of unchanged context lines to show around each added/removed line (default 3). Set to 0 to show only changed lines.
        start_page: The line number to start reading output from for pagination.
        max_lines: The maximum number of lines of output to return.
    """
    diff_text = ctx.deps.mr_request.diff()
    if not diff_text:
        return "No diff available."

    files = parse_diff_into_files(diff_text)
    if not files:
        return "No files found in diff."

    target_path = file_path.lstrip("/") if file_path else None

    result_parts: list[str] = []

    for header, content in files:
        new_path = None
        old_path = None
        for hline in header:
            hline_stripped = hline.rstrip("\n")
            if hline_stripped.startswith("+++ b/"):
                new_path = hline_stripped[6:]
            elif hline_stripped.startswith("--- a/"):
                old_path = hline_stripped[6:]

        if target_path and new_path != target_path and old_path != target_path:
            continue

        raw_lines = [l.rstrip("\n") for l in content]
        hunks = extract_hunks(raw_lines)
        if not hunks:
            continue

        file_output_parts: list[str] = []
        file_output_parts.extend(h.rstrip("\n") for h in header)

        for hunk in hunks:
            if start_line is not None and hunk.new_start + hunk.new_count < start_line:
                continue
            if end_line is not None and hunk.new_start > end_line:
                continue

            filtered_lines = _filter_hunk_lines(hunk, start_line, end_line, context_lines)
            file_output_parts.append(hunk.header)
            file_output_parts.extend(filtered_lines)

        if len(file_output_parts) > len(header):
            result_parts.append("\n".join(file_output_parts))

    if not result_parts:
        if target_path:
            return f"No diff found for file: {file_path}"
        return "No diff content matched the given filters."

    full_output = "\n".join(result_parts)
    numbered = inject_line_numbers(full_output)
    return paginate_text(numbered, start_page, max_lines)


def _filter_hunk_lines(
    hunk: DiffHunk,
    start_line: int | None,
    end_line: int | None,
    context_lines: int,
) -> list[str]:
    new_line = hunk.new_start
    line_new_numbers: list[int | None] = []
    change_indices: list[int] = []

    for i, line in enumerate(hunk.lines):
        if line.startswith("\\"):
            line_new_numbers.append(None)
            continue
        if line.startswith("-"):
            line_new_numbers.append(None)
            if _in_range(new_line, start_line, end_line, is_removed=True):
                change_indices.append(i)
        elif line.startswith("+"):
            line_new_numbers.append(new_line)
            if _in_range(new_line, start_line, end_line):
                change_indices.append(i)
            new_line += 1
        else:
            line_new_numbers.append(new_line)
            if _in_range(new_line, start_line, end_line):
                change_indices.append(i)
            new_line += 1

    if not change_indices:
        return []

    keep_indices: set[int] = set()
    for pos in change_indices:
        lo = max(0, pos - context_lines)
        hi = min(len(hunk.lines), pos + context_lines + 1)
        for idx in range(lo, hi):
            keep_indices.add(idx)

    result: list[str] = []
    prev: int | None = None
    for idx in sorted(keep_indices):
        if prev is not None and idx > prev + 1:
            result.append("  ...")
        result.append(hunk.lines[idx])
        prev = idx

    return result


def _in_range(
    new_line: int,
    start_line: int | None,
    end_line: int | None,
    is_removed: bool = False,
) -> bool:
    if is_removed:
        if start_line is not None and end_line is not None:
            return start_line <= new_line <= end_line + 1
        if start_line is not None:
            return new_line >= start_line - 1
        if end_line is not None:
            return new_line <= end_line + 1
        return True
    if start_line is not None and new_line < start_line:
        return False
    if end_line is not None and new_line > end_line:
        return False
    return True


def dependency_graph(
    ctx: RunContext[ReviewDeps],
    file_path: str | None = None,
    direction: str = "dependents",
    symbol: str | None = None,
    start_page: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    Query the dependency graph to find what a file imports or what files depend on it.

    Use this tool to understand the blast radius of a change — which files will be
    affected if a module is modified. Also useful for checking coupling depth.

    Args:
        file_path: Target file to query (e.g. "src/auth.ts"). None returns a summary of all modules.
        direction: "dependents" = files that import this file; "dependencies" = files this file imports.
        symbol: Filter to files that reference a specific exported symbol name.
        start_page: The line number to start reading output from for pagination.
        max_lines: The maximum number of lines of output to return.
    """
    graph = ctx.deps.dependency_graph
    if graph is None:
        return "Dependency graph is not available (not built or build failed)."

    if file_path is None:
        return paginate_text(_format_dep_graph(graph), start_page, max_lines)

    file_path = file_path.lstrip("/")
    mod = graph.modules.get(file_path)
    if mod is None:
        candidates = [p for p in graph.modules if p.endswith(file_path)]
        if len(candidates) == 1:
            file_path = candidates[0]
            mod = graph.modules[file_path]
        elif len(candidates) > 1:
            return f"Multiple matches for '{file_path}': {', '.join(candidates)}. Specify the full path."
        else:
            return f"File not found in dependency graph: {file_path}"

    if direction == "dependents":
        deps = graph.dependents.get(file_path, set())
        if not deps:
            return f"No dependents found for: {file_path}"
        result_lines = [f"Dependents of '{file_path}':"]
        for dep_path in sorted(deps):
            dep_mod = graph.modules.get(dep_path)
            if dep_mod is None:
                result_lines.append(f"  {dep_path}")
                continue
            if symbol:
                matching = [
                    imp.raw for imp in dep_mod.imports
                    if imp.resolved == file_path and symbol.lower() in imp.raw.lower()
                ]
                if not matching:
                    matching = [
                        imp.raw for imp in dep_mod.imports
                        if imp.resolved == file_path
                    ]
                    if not any(symbol.lower() == d.lower() for d in dep_mod.definitions):
                        continue
                result_lines.append(f"  {dep_path} (imports: {', '.join(matching)})")
            else:
                imported = [imp.raw for imp in dep_mod.imports if imp.resolved == file_path]
                suffix = f" (imports: {', '.join(imported)})" if imported else ""
                result_lines.append(f"  {dep_path}{suffix}")
        if len(result_lines) == 1:
            return f"No dependents found for: {file_path}"
        result_lines.append(f"\n{len(result_lines) - 1} files depend on {file_path}.")
        return paginate_text("\n".join(result_lines), start_page, max_lines)

    elif direction == "dependencies":
        if not mod.imports:
            return f"No imports found for: {file_path}"
        result_lines = [f"Dependencies of '{file_path}':"]
        for imp in mod.imports:
            status = imp.resolved if imp.resolved else "[unresolved]"
            result_lines.append(f"  {imp.raw} -> {status}")
        result_lines.append(f"\n{file_path} imports {len(mod.imports)} module(s).")
        return paginate_text("\n".join(result_lines), start_page, max_lines)

    else:
        return f"Invalid direction: '{direction}'. Use 'dependents' or 'dependencies'."


def update_todo(
    ctx: RunContext[ReviewDeps],
    action: str,
    issue_id: str,
    state: str | None = None,
    description: str | None = None,
) -> str:
    """
    Track issues through the 4-phase review workflow.

    Use this to keep an explicit checklist of every issue you discover,
    so you don't lose or double-count findings during a long review.

    Args:
        action: "add" to log a new issue, "update" to change state/description,
                "drop" to discard (false positive), "list" to see all tracked issues.
        issue_id: Short unique identifier for this issue (e.g. "auth-sqli-1", "perf-n1-query").
        state: Current pipeline state. One of:
               triaged — risk scored, queued
               hypothesis — claim formed
               falsified — disproven by tool, ready to discard
               confirmed — survived falsification
               dropped — removed (false positive, low confidence, etc.)
        description: What was found, what changed, or what tool result was.
    """
    todo = ctx.deps.todo_items

    if action == "list":
        if not todo:
            return "No issues tracked yet."
        lines = []
        for i, item in enumerate(todo, 1):
            lines.append(f"  [{item.get('state', '?')}] {item['issue_id']}: {item.get('description', '')}")
        return "Tracked issues:\n" + "\n".join(lines)

    if action == "drop":
        for item in todo:
            if item["issue_id"] == issue_id:
                item["state"] = "dropped"
                return f"[TODO] {issue_id} → dropped"
        return f"[TODO] Issue '{issue_id}' not found."

    if action == "add":
        if any(item["issue_id"] == issue_id for item in todo):
            return f"[TODO] Issue '{issue_id}' already exists. Use action='update' to modify."
        todo.append(dict(issue_id=issue_id, state=state or "triaged", description=description or ""))
        return f"[TODO] Added {issue_id} [{state or 'triaged'}]"

    if action == "update":
        for item in todo:
            if item["issue_id"] == issue_id:
                if state:
                    item["state"] = state
                if description:
                    item["description"] = description
                return f"[TODO] {issue_id} → [{item['state']}] {item['description']}"
        return f"[TODO] Issue '{issue_id}' not found. Use action='add' first."

    return f"[TODO] Unknown action: '{action}'. Use add, update, drop, or list."


shared_tools = [
    Tool(fetch_file_content),
    Tool(list_files),
    Tool(scan_code),
    Tool(execute_command),
    Tool(vector_search),
    Tool(suggest_bot_improvement),
    Tool(diff_context),
    Tool(update_todo),
]
