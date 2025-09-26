from urllib.parse import urlparse, quote


def extract_gitlab_info(url):
    parsed_url = urlparse(url)

    # Extract protocol
    protocol = parsed_url.scheme

    # Extract host and port
    host = parsed_url.netloc

    # Extract project path and merge request id
    path_parts = parsed_url.path.split('/')

    # Find the project path (from first non-empty part until before "-/merge_requests")
    project_parts = []
    for i in range(1, len(path_parts)):  # Start from index 1 (after first empty string)
        if path_parts[i] == '-':
            break
        if path_parts[i]:  # Skip empty strings
            project_parts.append(path_parts[i])

    project_path = '/'.join(project_parts)

    # Extract merge request id
    mr_id = None
    for i in range(len(path_parts)):
        if path_parts[i] == 'merge_requests' and i + 1 < len(path_parts):
            mr_id = path_parts[i + 1]
            break

    return [f"{protocol}://{host}", quote(project_path, safe=''), int(mr_id)]