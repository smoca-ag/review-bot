from review_bot.models import ReviewDeps
from review_bot.utils.diff import DiffHunk, extract_hunks, parse_diff_into_files
from review_bot.utils.text import inject_line_numbers, paginate_text
from pydantic_ai import RunContext


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
        file_path: Filter to a single file path (e.g. "src/auth.ts"). None returns all files.
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