import json
import os
from urllib.parse import quote, urlparse

import requests

from review_bot.backend.base_backend import BaseBackend


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

    if mr_id is None:
        raise ValueError(
            f"Could not extract merge request ID from URL: {url}. "
            f"Expected URL format: https://gitlab.example.com/group/project/-/merge_requests/19"
        )

    try:
        mr_id = int(mr_id)
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid merge request ID '{mr_id}' in URL: {url}. Expected a numeric ID."
        )

    return [f"{protocol}://{host}", quote(project_path, safe=""), mr_id]


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
        self.current_user_id = self.get_current_user_id()
        self.versions = self.get_versions()
        self.discussions = self.get_discussion()
        self.diff_response = self.get_merge_request_diff()
        self.mr = self.get_mr()
        self.fetch_repository()


    def get_current_user_id(self):
        user_url = f"{self.gitlab_url}/api/v4/user"
        user_resp = requests.get(
            user_url, headers={"PRIVATE-TOKEN": self.private_token}
        )
        if user_resp.ok:
            return user_resp.json().get("id")
        self.logger.error("Could not fetch current user info")
        return None

    def is_open(self) -> bool:
        if not hasattr(self, "mr") or not self.mr:
            return False
        return self.mr.get("state") == "opened"

    def is_draft(self) -> bool:
        if not hasattr(self, "mr") or not self.mr:
            return False
        return self.mr.get("work_in_progress", False) or self.mr.get("draft", False)

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

    def get_paginated_response(self, url):
        headers = {"PRIVATE-TOKEN": self.private_token}
        results = []
        while url:
            response = requests.get(url, headers=headers)
            if not response.ok:
                self.logger.error(f"Error fetching {url}: {response}")
                break

            data = response.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                # If it's not a list, pagination might not apply in the expected way
                return data

            url = response.links.get("next", {}).get("url")
        return results

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

        from opentelemetry import trace

        tracer = trace.get_tracer(__name__)

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

        with tracer.start_as_current_span("project_checkout") as span:
            span.set_attribute("gitlab.project_id", self.project_id)
            span.set_attribute("gitlab.merge_request_iid", self.merge_request_iid)
            span.set_attribute("gitlab.repo_dir", self.repo_dir)

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
        return self.get_paginated_response(url)

    def post_line_review(self, text, new_path, new_position):
        if new_path == "/dev/null" or not new_path:
            return  # Can't review a completely deleted file

        new_path = new_path.lstrip("/")

        # --- THE FIX: Let the coordinate resolver establish truth ---
        old_path, old_position = self._resolve_diff_coordinates(new_path, new_position)

        # Ensure we aren't doubling up on discussions
        def get_pos(note):
            pos = note.get("position")
            return pos if pos is not None else {}

        if any(
                get_pos(note).get("new_path") == new_path
                and get_pos(note).get("new_line") == new_position
                and note.get("author", {}).get("id") == self.current_user_id
                for d in self.discussions
                if d.get("notes")
                for note in d["notes"]
        ):
            self.logger.info(
                f"Already a discussion by the bot on path {new_path} and position {new_position}"
            )
            return

        # Build position mapping payload safely
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

        # Clean out any keys containing None (e.g., old_line on an added line)
        position = {k: v for k, v in position.items() if v is not None}

        payload = {"body": text, "position": position}
        print(json.dumps(payload))

        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload)
        if not response.ok:
            self.logger.error(f"Error posting inline discussion note to GitLab: {response.text}")

    def post_review(self, text):
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }

        current_user_id = self.current_user_id
        if not current_user_id:
            # Fallback if load() didn't get it
            user_url = f"{self.gitlab_url}/api/v4/user"
            user_resp = requests.get(
                user_url, headers={"PRIVATE-TOKEN": self.private_token}
            )
            if not user_resp.ok:
                self.logger.error("Could not fetch current user info")
                return
            current_user_id = user_resp.json().get("id")

        # 2. Get existing notes
        notes_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/notes"
        notes_resp = requests.get(
            notes_url,
            headers={"PRIVATE-TOKEN": self.private_token},
            params={"per_page": 100},
        )

        existing_notes = []
        if notes_resp.ok:
            for note in notes_resp.json():
                if (
                    not note.get("system")
                    and note.get("author", {}).get("id") == current_user_id
                ):
                    # Filter out inline comments (DiffNote)
                    if note.get("type") != "DiffNote":
                        existing_notes.append(note)

        # 3. Update or post
        if existing_notes:
            # Update the first one
            note_to_update = existing_notes[0]
            update_url = f"{notes_url}/{note_to_update['id']}"
            update_resp = requests.put(update_url, headers=headers, json={"body": text})
            if not update_resp.ok:
                self.logger.error(
                    f"Error updating general MR note: {update_resp.status_code}"
                )
            else:
                self.logger.info("Successfully updated existing general MR note.")

            # Delete the rest
            for note in existing_notes[1:]:
                delete_url = f"{notes_url}/{note['id']}"
                del_resp = requests.delete(
                    delete_url, headers={"PRIVATE-TOKEN": self.private_token}
                )
                if not del_resp.ok:
                    self.logger.error(
                        f"Error deleting old general MR note: {del_resp.status_code}"
                    )
        else:
            # Post new
            payload = {"body": text}
            response = requests.post(notes_url, headers=headers, json=payload)
            if not response.ok:
                self.logger.error(
                    f"Error posting general MR note to GitLab: {response.status_code}"
                )
            else:
                self.logger.info("Successfully posted new general MR note.")

    def _resolve_diff_coordinates(self, target_new_path, target_new_line):
        """
        Parses self.diff_response to find the true historical old_path (handling renames)
        and maps target_new_line to its corresponding old_line based on diff hunks.
        """
        if not self.diff_response:
            return target_new_path, None

        lines = self.diff_response.splitlines()
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
            if line.startswith('@@'):
                try:
                    # Extract starting coordinates: @@ -old_start,len +new_start,len @@
                    parts = line.split(' ')
                    old_start = int(parts[1].split(',')[0].replace('-', ''))
                    new_start = int(parts[2].split(',')[0].replace('+', ''))
                    old_line_counter = old_start
                    new_line_counter = new_start
                except (IndexError, ValueError):
                    continue
                continue

            # Check if we reached the line flagged by your linter/bot
            if new_line_counter == target_new_line:
                if line.startswith('+'):
                    # It's an added or modified line. GitLab requires old_line to be blank.
                    return old_path, None
                elif line.startswith(' '):
                    # It's an unmodified context line. Return its matched historical line.
                    return old_path, old_line_counter

                    # Move line counters forward depending on the diff modification type
            if line.startswith('+'):
                new_line_counter += 1
            elif line.startswith('-'):
                old_line_counter += 1
            elif line.startswith(' '):
                old_line_counter += 1
                new_line_counter += 1

        return old_path, None