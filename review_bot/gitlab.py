import os
from urllib.parse import quote, urlparse

import requests

from review_bot.base_backend import BaseBackend


def extract_gitlab_info(url):
    parsed_url = urlparse(url)

    # Extract protocol
    protocol = parsed_url.scheme

    # Extract host and port
    host = parsed_url.netloc

    # Extract project path and merge request id
    path_parts = parsed_url.path.split("/")

    # Find the project path (from first non-empty part until before "-/merge_requests")
    project_parts = []
    for i in range(1, len(path_parts)):  # Start from index 1 (after first empty string)
        if path_parts[i] == "-":
            break
        if path_parts[i]:  # Skip empty strings
            project_parts.append(path_parts[i])

    project_path = "/".join(project_parts)

    # Extract merge request id
    mr_id = None
    for i in range(len(path_parts)):
        if path_parts[i] == "merge_requests" and i + 1 < len(path_parts):
            mr_id = path_parts[i + 1]
            break

    return [f"{protocol}://{host}", quote(project_path, safe=""), int(mr_id)]


class Gitlab(BaseBackend):
    def __init__(self, logger, url):
        super().__init__()
        self.logger = logger
        [self.gitlab_url, self.project_id, self.merge_request_iid] = (
            extract_gitlab_info(url)
        )
        if not self.gitlab_url:
            raise ValueError(
                "Error: GitLab URL must be provided (https://gitlab.example.com/example-group/example-project/-/merge_requests/19)"
            )
        self.private_token = os.getenv("GITLAB_API_TOKEN")
        if not self.private_token:
            raise ValueError("Error: GITLAB_API_TOKEN environment variable is not set")

    def load(self):
        self.versions = self.get_versions()
        self.discussions = self.get_discussion()
        self.diff_response = self.get_merge_request_diff()
        self.mr = self.get_mr()
        self.fetch_repository()

    def diff(self):
        return self.diff_response

    def title(self):
        return self.mr.get("title", "")

    def description(self):
        return self.mr.get("description", "")

    def get_versions(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/versions"
        return self.get_json_response(url)

    def get_json_response(self, url):
        headers = {"PRIVATE-TOKEN": self.private_token}
        response = requests.get(url, headers=headers)
        if not response.ok:
            self.logger.error(f"Error fetching {url}: {response}")
            return None
        return response.json()

    def get_text_response(self, url):
        headers = {"PRIVATE-TOKEN": self.private_token}
        response = requests.get(url, headers=headers)
        if not response.ok:
            self.logger.error(f"Error fetching {url}: {response}")
            return None
        return response.text

    def get_merge_request_diff(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/raw_diffs"
        return self.get_text_response(url)

    def get_mr(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}"
        return self.get_json_response(url)

    def get_project(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}"
        return self.get_json_response(url)

    def fetch_repository(self):
        import subprocess
        import tempfile
        import urllib.parse

        self.repo_dir = tempfile.mkdtemp()

        project = self.get_project()
        if not project or "http_url_to_repo" not in project:
            self.logger.error("Could not get project details for cloning.")
            return

        repo_url = project["http_url_to_repo"]
        parsed = urllib.parse.urlparse(repo_url)
        clone_url = parsed._replace(
            netloc=f"oauth2:{self.private_token}@{parsed.netloc}"
        ).geturl()

        subprocess.check_call(["git", "init", self.repo_dir])
        subprocess.check_call(
            ["git", "remote", "add", "origin", clone_url], cwd=self.repo_dir
        )

        subprocess.check_call(
            [
                "git",
                "fetch",
                "--depth",
                "1",
                "origin",
                f"refs/merge-requests/{self.merge_request_iid}/head:mr-head",
            ],
            cwd=self.repo_dir,
        )

        target_branch = self.mr.get("target_branch")
        if target_branch:
            subprocess.check_call(
                [
                    "git",
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    f"refs/heads/{target_branch}:target-branch",
                ],
                cwd=self.repo_dir,
            )

        subprocess.check_call(["git", "checkout", "mr-head"], cwd=self.repo_dir)

    def cleanup(self):
        import shutil

        if getattr(self, "repo_dir", None):
            try:
                shutil.rmtree(self.repo_dir)
                if hasattr(self, "logger"):
                    self.logger.info(f"Cleaned up repo directory: {self.repo_dir}")
            except Exception as e:
                if hasattr(self, "logger"):
                    self.logger.error(f"Failed to clean up repo directory: {e}")
            finally:
                self.repo_dir = None

        super().cleanup()

    def get_discussion(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        return self.get_json_response(url)

    def post_line_review(self, text, old_path, new_path, old_position, new_position):
        if new_path == "/dev/null":
            new_path = None
        if old_path == "/dev/null":
            old_path = None

        # Ensure we aren't doubling up on discussions
        if any(
            d["notes"][0].get("position", {}).get("new_path") == new_path
            and d["notes"][0].get("position", {}).get("new_line") == new_position
            for d in self.discussions
            if d.get("notes")
        ):
            self.logger.info(
                f"Already a discussion on path {new_path} and position {new_position}"
            )
            return

        position = {
            "new_path": new_path,
            "old_path": old_path,
            "base_sha": self.versions[0]["base_commit_sha"],
            "start_sha": self.versions[0]["start_commit_sha"],
            "head_sha": self.versions[0]["head_commit_sha"],
            "position_type": "text",
            "new_line": new_position,
            "old_line": old_position,
        }

        # Note: GitLab Draft Notes API uses 'note' instead of 'body'
        payload = {"note": text, "position": position}
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/draft_notes"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload)
        if not response.ok:
            self.logger.error(f"Error posting inline draft note to GitLab: {response}")

    def post_review(self, text):
        # Using the standard /notes endpoint instead of /draft_notes
        payload = {"body": text}
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/notes"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload)
        if not response.ok:
            self.logger.error(f"Error posting general MR note to GitLab: {response.status_code}")

    def publish_reviews(self):
        """
        Publishes all pending draft notes for this merge request in one pass.
        """
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/draft_notes/bulk_publish"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers)
        if not response.ok:
            self.logger.error(
                f"Error bulk-publishing draft notes to GitLab: {response.text}"
            )
        else:
            self.logger.info("Successfully published all draft notes.")

    def _debug_publish_individually(self):
        """
        Fetches all pending draft notes and publishes them one by one via PUT.
        """
        base_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/draft_notes"
        headers = {"PRIVATE-TOKEN": self.private_token}

        # 1. Fetch pending draft notes
        get_resp = requests.get(base_url, headers=headers)
        if not get_resp.ok:
            self.logger.error("Could not fetch draft notes for debugging.")
            return

        notes = get_resp.json()
        if not notes:
            self.logger.info("No draft notes found to publish.")
            return

        # 2. Try publishing them one by one
        for note in notes:
            note_id = note.get("id")
            pub_url = f"{base_url}/{note_id}/publish"

            # Note: Publishing a single draft note requires a PUT request, not POST.
            pub_resp = requests.put(pub_url, headers=headers)

            if pub_resp.ok:
                self.logger.info(f"Successfully published draft note {note_id}.")
            else:
                self.logger.error(f"FAILED to publish draft note {note_id}. Status: {pub_resp.status_code}")
                self.logger.error(f"Problematic note position data: {note.get('position', 'No position data found')}")