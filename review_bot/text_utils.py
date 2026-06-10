import re

_MAX_LINE_LENGTH = 150


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
            # "\\ No newline at end of file" – don't increment line counters
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
    max_lines: int,
    max_line_length: int = _MAX_LINE_LENGTH,
    add_line_numbers: bool = False,
) -> str:
    lines = text.splitlines()
    total = len(lines)
    start_idx = max(0, start_line - 1)
    end_idx = min(start_idx + max_lines, total)
    chunk = lines[start_idx:end_idx]
    processed_chunk = []
    for i, line in enumerate(chunk):
        if len(line) > max_line_length:
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


def resolve_diff_coordinates(
    diff_response: str | None, target_new_path: str, target_new_line: int
) -> tuple[str, int | None]:
    """
    Parses a diff to find the true historical old_path (handling renames)
    and maps target_new_line to its corresponding old_line based on diff hunks.
    """
    if not diff_response:
        return target_new_path, None

    lines = diff_response.splitlines()
    i = 0
    num_lines = len(lines)

    old_path = target_new_path
    diff_hunk_lines = []
    found_file = False

    # Clean up target path matching
    target_new_path = target_new_path.lstrip("/") if target_new_path else ""

    # 1. Isolate the target file's diff block and extract the original path
    while i < num_lines:
        line = lines[i]
        if line.startswith("+++ b/") and line[6:].lstrip("/") == target_new_path:
            found_file = True
            # Look at the immediate preceding line for the historical path
            if i > 0 and lines[i - 1].startswith("--- a/"):
                extracted_old = lines[i - 1][6:].lstrip("/")
                if extracted_old != "dev/null":
                    old_path = extracted_old

            # Collect the diff patch lines for this specific file
            i += 1
            while i < num_lines and not lines[i].startswith("diff --git"):
                diff_hunk_lines.append(lines[i])
                i += 1
            break
        i += 1

    if not found_file:
        return old_path, None

    # 2. Reconstruct line numbers by parsing unified diff hunks (@@)
    old_line_counter = 0
    new_line_counter = 0

    for line in diff_hunk_lines:
        if line.startswith("@@"):
            try:
                # Extract starting coordinates: @@ -old_start,len +new_start,len @@
                parts = line.split(" ")
                old_start = int(parts[1].split(",")[0].replace("-", ""))
                new_start = int(parts[2].split(",")[0].replace("+", ""))
                old_line_counter = old_start
                new_line_counter = new_start
            except (IndexError, ValueError):
                continue
            continue

        # Check if we reached the line flagged by your linter/bot
        if new_line_counter == target_new_line:
            if line.startswith("+"):
                # It's an added or modified line. GitLab requires old_line to be blank.
                return old_path, None
            elif line.startswith(" "):
                # It's an unmodified context line. Return its matched historical line.
                return old_path, old_line_counter

        # Move line counters forward depending on the diff modification type
        if line.startswith("+"):
            new_line_counter += 1
        elif line.startswith("-"):
            old_line_counter += 1
        elif line.startswith(" "):
            old_line_counter += 1
            new_line_counter += 1

    return old_path, None
