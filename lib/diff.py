import re
def process_diff(diff_text):
    """
     Process a raw diff and yield information about each line change including file paths.

     Yields:
         tuple: (type, old_line_number, new_line_number, content, old_path, new_path)
     """
    lines = diff_text.splitlines(True)

    # Track current file paths
    old_path = None
    new_path = None

    # Track positions
    old_line_num = 0
    new_line_num = 0
    in_hunk = False

    for line in lines:
        if line.startswith('---'):
            # Extract old path from --- line
            match = re.match(r'^--- [ab]/(.+)$', line.strip())
            if match:
                old_path = match.group(1)
            else:
                match = re.match(r'^--- (.+)$', line.strip())
                if match:
                    old_path = match.group(1)

        elif line.startswith('+++'):
            # Extract new path from +++ line
            match = re.match(r'^\+\+\+ [ab]/(.+)$', line.strip())
            if match:
                new_path = match.group(1)
            else:
                match = re.match(r'^\+\+\+ (.+)$', line.strip())
                if match:
                    new_path = match.group(1)

        elif line.startswith('@@'):
            # Parse hunk header: @@ -1,3 +1,4 @@
            parts = line.strip().split()
            if len(parts) >= 3:
                old_info = parts[1][1:]  # Remove leading '-'
                new_info = parts[2][1:]  # Remove leading '+'

                old_start, _ = map(int, old_info.split(','))
                new_start, _ = map(int, new_info.split(','))

                old_line_num = old_start
                new_line_num = new_start
                in_hunk = True

        elif line.startswith('+') and not line.startswith('+++'):
            yield ('added', None, new_line_num, line[1:], old_path, new_path)
            new_line_num += 1

        elif line.startswith('-') and not line.startswith('---'):
            yield ('deleted', old_line_num, None, line[1:], old_path, new_path)
            old_line_num += 1

        elif line.startswith(' ') or line.startswith('\\'):
            yield ('unchanged', old_line_num, new_line_num, line[1:], old_path, new_path)
            old_line_num += 1
            new_line_num += 1

def paths_from_diff(diff_content):
    paths = set()
    for change_type, old_pos, new_pos, content, old_path, new_path in process_diff(diff_content):
        paths.add(new_path)
    return paths
