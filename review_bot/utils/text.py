"""General text utilities: CDATA wrapping, line numbering, chunking, pagination."""

import re
import os

_MAX_LINE_LENGTH = int(os.getenv("MAX_LINE_LENGTH", "150"))
_MAX_FILE_LINES = int(os.getenv("MAX_LINES", "200"))


def wrap_in_cdata(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    safe_text = text.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe_text}]]>"


def inject_line_numbers(diff_text: str) -> str:
    result = []
    current_new_line = None
    for line in diff_text.splitlines():
        if line.startswith("@@ "):
            match = re.search(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)?(?: @@|\s.*)", line)
            if match:
                current_new_line = int(match.group(1))
            result.append(line)
        elif line.startswith("---") or line.startswith("+++"):
            result.append(line)
        elif line.startswith("\\"):
            result.append(line)
        elif line.startswith("+"):
            if current_new_line is not None:
                result.append(f"{current_new_line:4d} | {line}")
                current_new_line += 1
            else:
                result.append(line)
        elif line.startswith("-"):
            result.append(line)
        else:
            if current_new_line is not None and not line.startswith(
                ("diff ", "index ")
            ):
                result.append(f"{current_new_line:4d} | {line}")
                current_new_line += 1
            else:
                result.append(line)
    return "\n".join(result)


def chunk_text(
    text: str, file_path: str, chunk_size: int = 50, overlap: int = 10
) -> list[tuple[str, str, int]]:
    lines = text.splitlines()
    chunks: list[tuple[str, str, int]] = []
    if not lines:
        return chunks
    i = 0
    while i < len(lines):
        chunk_lines = lines[i : i + chunk_size]
        chunk_text = "\n".join(chunk_lines)
        chunk_id = f"{file_path}:chunk-{i}"
        chunks.append((chunk_id, chunk_text, i + 1))
        i += chunk_size - overlap
    return chunks


def paginate_text(
    text: str,
    start_line: int,
    max_lines: int | None,
    max_line_length: int | None = _MAX_LINE_LENGTH,
    add_line_numbers: bool = False,
) -> str:
    """Slice text into a readable page, optionally numbering and truncating lines.

    Args:
        text: Full text to paginate.
        start_line: 1-indexed line to start reading from.
        max_lines: Maximum number of lines to return; ``None`` uses the
            ``MAX_LINES`` default.
        max_line_length: Per-line truncation limit; ``None`` disables
            truncation entirely.
        add_line_numbers: Prefix each returned line with its line number.
    """
    max_lines = _MAX_FILE_LINES if max_lines is None else max_lines
    lines = text.splitlines()
    total = len(lines)
    start_idx = max(0, start_line - 1)
    end_idx = min(start_idx + max_lines, total)
    chunk = lines[start_idx:end_idx]
    processed_chunk = []
    for i, line in enumerate(chunk):
        if max_line_length is not None and len(line) > max_line_length:
            line = line[: max_line_length - 3] + "..."
        if add_line_numbers:
            processed_chunk.append(f"{i + start_line:4d} | {line}")
        else:
            processed_chunk.append(line)
    result = "\n".join(processed_chunk)
    remaining_lines = total - end_idx
    if remaining_lines > 0:
        result += f"\n\n... (truncated. {remaining_lines} more lines. Call again with start_line={end_idx + 1} to continue.)"
    return result


def is_binary(content: bytes) -> bool:
    return b"\x00" in content