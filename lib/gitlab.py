import os

import requests
import urllib
import base64
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

class Gitlab():
    def __init__(self, logger, url):
        self.logger = logger
        [self.gitlab_url, self.project_id, self.merge_request_iid] = extract_gitlab_info(url)
        if not self.gitlab_url:
            raise ValueError("Error: GitLab URL must be provided (https://gitlab.example.com/example-group/example-project/-/merge_requests/19)")
        self.private_token = os.getenv('GITLAB_API_TOKEN')
        if not self.private_token:
            raise ValueError("Error: GITLAB_API_TOKEN environment variable is not set")
    def load(self):
        self.versions = self.get_versions()
        self.discussions = self.get_discussion()
        self.diff_response = self.get_merge_request_diff()
        self.mr = self.get_mr()

    def diff(self):
        return self.diff_response

    def title(self):
        return self.mr['title']


    def get_files(self, paths):
        paths_dict = {}
        for path in paths:
            paths_dict[path] = self.get_file(path)
        return paths_dict

    def get_versions(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/versions"
        return self.get_json_response(url)


    def get_json_response(self, url):
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }
        response = requests.get(url, headers=headers)
        if not response.ok:
            self.logger.error(f"Error fetching {url}: {response}")
            return None
        return response.json()

    def get_text_response(self, url):
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }
        response = requests.get(url, headers=headers)
        if not response.ok:
            self.logger.error(f"Error fetching {url}: {response}")
            return None
        return response.text

    def get_merge_request_diff(self):
        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/raw_diffs"
        return self.get_text_response(url)


    def get_mr(self):
        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}"
        return self.get_json_response(url)


    def get_file(self, file_path):
        """
        Fetches the content of a file from GitLab at a specific commit.
        """
        commit_sha = self.versions[0]["head_commit_sha"]
        # URL-encode the file path to handle special characters
        encoded_file_path = urllib.parse.quote_plus(file_path)
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/repository/files/{encoded_file_path}?ref={commit_sha}"
        response = self.get_json_response(url)
        if not response:
            return None
        content_base64 = response['content']
        decoded_content = base64.b64decode(content_base64).decode('utf-8')
        return decoded_content

    def get_discussion(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        return self.get_json_response(url)

    def post_review_as_inline_comments(self,payload):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json"
        }
        response = requests.post(url, headers=headers, json=payload)
        if not response.ok:
            self.logger.error(f"Error posting inline comment to GitLab: {response}")
    def post_review(self, text, old_path, new_path, old_position, new_position):

        if new_path == "/dev/null":
            new_path = None
        if old_path == "/dev/null":
            old_path = None
        if any(
                # For discussions that pass the filter, safely access the rest
                d['notes'][0].get('position', {}).get('new_path') == new_path and
                d['notes'][0].get('position', {}).get('new_line') == new_position
                # The filter: only process discussions where 'notes' is a non-empty list
                for d in self.discussions if d.get('notes')
        ):
            self.logger.info(f"Already a discussion on path {new_path} and position {new_position}")
            return

        position = {
            "new_path": new_path,
            "old_path": old_path,
            "base_sha": self.versions[0]["base_commit_sha"],
            "start_sha": self.versions[0]["start_commit_sha"],
            "head_sha": self.versions[0]["head_commit_sha"],
            "position_type": "text",
            "new_line": new_position,
            "old_line": old_position
        }
        payload = {"body": text, "position": position}
        self.post_review_as_inline_comments(payload)





