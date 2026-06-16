"""Diff parsing, truncation, and coordinate resolution utilities."""

import re
from dataclasses import dataclass, field

from review_bot.utils.text import _MAX_FILE_LINES, _MAX_LINE_LENGTH


@dataclass
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[str] = field(default_factory=list)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def extract_hunks(file_content_lines: list[str]) -> list[DiffHunk]:
    hunks: list[DiffHunk] = []
    current: DiffHunk | None = None
    for line in file_content_lines:
        stripped = line.rstrip("\n")
        m = _HUNK_RE.match(stripped)
        if m:
            current = DiffHunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2) or 1),
                new_start=int(m.group(3)),
                new_count=int(m.group(4) or 1),
                header=stripped,
            )
            hunks.append(current)
        elif current is not None:
            current.lines.append(stripped)
    return hunks


def parse_diff_into_files(diff_text: str) -> list[tuple[list[str], list[str]]]:
    """Parse a unified diff into a list of (file_header_lines, content_lines) tuples.

    Each tuple contains:
    - file_header_lines: the ``diff --git``, ``index``, ``---``, ``+++`` lines
    - content_lines: the ``@@`` hunk headers and diff content lines
    """
    files = []
    lines = diff_text.splitlines(keepends=True)
    i = 0
    num_lines = len(lines)

    while i < num_lines:
        line = lines[i]
        if line.startswith("diff --git"):
            header = []
            while i < num_lines:
                if lines[i].startswith("@@ "):
                    break
                header.append(lines[i])
                i += 1
            content = []
            while i < num_lines and not lines[i].startswith("diff --git"):
                content.append(lines[i])
                i += 1
            if header:
                files.append((header, content))
        else:
            i += 1

    return files


def _truncate_long_line(line: str, max_length: int) -> str:
    """Truncate a single diff line if it exceeds *max_length*.

    Diff lines start with a prefix character (``+``, ``-``, `` ``).
    The prefix is preserved; only the payload is shortened.

    Hunk headers (``@@``) are never truncated so that downstream
    line-number injection still works.
    """
    if len(line) <= max_length:
        return line

    payload = line.rstrip("\n")
    has_newline = line.endswith("\n")

    prefix = payload[0]
    body = payload[1:]

    if prefix == "@":
        return line

    skipped = len(body) - (max_length - len(prefix) - 40)
    if skipped < 0:
        skipped = 0

    keep_each = max(20, (max_length - len(prefix) - 40) // 2)
    truncated_body = (
        body[:keep_each] + f"... [truncated {skipped} chars] ..." + body[-keep_each:]
    )

    result = prefix + truncated_body
    if has_newline:
        result += "\n"
    return result


def truncate_large_diff_files(
    diff_text: str,
    max_lines: int | None = None,
    max_line_length: int | None = None,
) -> str:
    """Truncate per-file sections of a unified diff that exceed *threshold* lines.

    Two independent mechanisms are applied:

    1. **Line-count truncation** — files whose diff content exceeds
       *max_lines* are reduced to the first *keep_head* lines, with a
       marker indicating how many lines were skipped.

    2. **Line-length truncation** — any individual diff line longer than
       *max_line_length* is shortened in-place.  Hunk headers (``@@``) are
       never touched.

    Args:
        diff_text: A unified diff (e.g. from ``git diff`` or the GitLab API).
        max_lines: Maximum content lines per file before truncation.
                   Defaults to ``MAX_LINES`` env var (200).
        max_line_length: Maximum characters per diff line.
                         Defaults to ``MAX_LINE_LENGTH`` env var (150).

    Returns the (possibly truncated) diff text.
    """
    if max_line_length is None:
        max_line_length = _MAX_LINE_LENGTH
    if max_lines is None:
        max_lines = _MAX_FILE_LINES

    files = parse_diff_into_files(diff_text)
    if not files:
        return diff_text

    result_parts = []
    for header, content in files:
        file_path = "unknown"
        for hline in header:
            if hline.startswith("+++ b/"):
                file_path = hline[6:].rstrip()
                break

        content = [_truncate_long_line(line, max_line_length) for line in content]

        keep_head = max(10, max_lines // 10)
        if len(content) > max_lines:
            head = content[:keep_head]
            skipped = len(content) - keep_head

            truncation_marker = (
                f"  ... [TRUNCATED {skipped} lines to save tokens. "
                f"Total diff for {file_path} was {len(content)} lines.] ...\n"
            )
            result_parts.extend(header)
            result_parts.extend(head)
            result_parts.append(truncation_marker)
        else:
            result_parts.extend(header)
            result_parts.extend(content)

    return "".join(result_parts)


def resolve_diff_coordinates(
    diff_response: str | None, target_new_path: str, target_new_line: int
) -> tuple[str, int | None]:
    """Parse a diff to find the historical old_path (handling renames)
    and map target_new_line to its corresponding old_line based on diff hunks.
    """
    if not diff_response:
        return target_new_path, None

    lines = diff_response.splitlines()
    i = 0
    num_lines = len(lines)

    old_path = target_new_path
    diff_hunk_lines = []
    found_file = False

    target_new_path = target_new_path.lstrip("/") if target_new_path else ""

    while i < num_lines:
        line = lines[i]
        if line.startswith("+++ b/") and line[6:].lstrip("/") == target_new_path:
            found_file = True
            if i > 0 and lines[i - 1].startswith("--- a/"):
                extracted_old = lines[i - 1][6:].lstrip("/")
                if extracted_old != "dev/null":
                    old_path = extracted_old

            i += 1
            while i < num_lines and not lines[i].startswith("diff --git"):
                diff_hunk_lines.append(lines[i])
                i += 1
            break
        i += 1

    if not found_file:
        return old_path, None

    old_line_counter = 0
    new_line_counter = 0

    for line in diff_hunk_lines:
        if line.startswith("@@"):
            try:
                parts = line.split(" ")
                old_start = int(parts[1].split(",")[0].replace("-", ""))
                new_start = int(parts[2].split(",")[0].replace("+", ""))
                old_line_counter = old_start
                new_line_counter = new_start
            except (IndexError, ValueError):
                continue
            continue

        if line.startswith("\\"):
            continue

        if new_line_counter == target_new_line:
            if line.startswith("+"):
                return old_path, None
            elif line.startswith(" "):
                return old_path, old_line_counter

        if line.startswith("+"):
            new_line_counter += 1
        elif line.startswith("-"):
            old_line_counter += 1
        elif line.startswith(" "):
            old_line_counter += 1
            new_line_counter += 1

    return old_path, None