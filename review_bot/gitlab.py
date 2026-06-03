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
        self.clear_existing_draft_notes()
        self.diff_response = self.get_merge_request_diff()
        self.mr = self.get_mr()
        self.fetch_repository()

    def clear_existing_draft_notes(self):
        draft_notes = self.get_draft_notes()
        base_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/draft_notes"
        headers = {"PRIVATE-TOKEN": self.private_token}
        for note in draft_notes:
            if note.get("author", {}).get("id") == self.current_user_id:
                note_id = note.get("id")
                del_url = f"{base_url}/{note_id}"
                resp = requests.delete(del_url, headers=headers)
                if not resp.ok:
                    self.logger.error(f"Failed to delete stale draft note {note_id}")

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
        return self.get_paginated_response(url)

    def get_draft_notes(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/draft_notes"
        return self.get_paginated_response(url)

    def post_line_review(self, text, old_path, new_path, old_position, new_position):
        if new_path == "/dev/null":
            new_path = None
        elif new_path:
            new_path = new_path.lstrip("/")

        if old_path == "/dev/null":
            old_path = None
        elif old_path:
            old_path = old_path.lstrip("/")

        # Ensure we aren't doubling up on discussions
        def get_pos(note):
            pos = note.get("position")
            return pos if pos is not None else {}

        def normalize_text(t):
            return t.replace("\r\n", "\n").strip() if t else ""

        discussions = getattr(self, "discussions", None) or []
        if any(
            get_pos(note).get("new_path") == new_path
            and get_pos(note).get("new_line") == new_position
            and note.get("author", {}).get("id") == self.current_user_id
            and normalize_text(note.get("body")) == normalize_text(text)
            for d in discussions
            if d.get("notes")
            for note in d["notes"]
        ):
            self.logger.info(
                f"Already a discussion by the bot on path {new_path} and position {new_position} with same text"
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
            self.publish_individually()
        else:
            self.logger.info("Successfully published all draft notes.")
        self.clear_existing_draft_notes()


    def publish_individually(self):
        """
        Fetches all pending draft notes and publishes them one by one via PUT.
        """
        notes = self.get_draft_notes()

        headers = {"PRIVATE-TOKEN": self.private_token}
        # 2. Try publishing them one by one
        for note in notes:
            note_id = note.get("id")
            pub_url = f"{base_url}/{note_id}/publish"

            # Note: Publishing a single draft note requires a PUT request, not POST.
            pub_resp = requests.put(pub_url, headers=headers)

            if pub_resp.ok:
                self.logger.info(f"Successfully published draft note {note_id}.")
            else:
                del_url = f"{base_url}/{note_id}"
                requests.delete(del_url, headers=headers)
                self.logger.error(
                    f"FAILED to publish draft note {note_id}. Status: {pub_resp.status_code}"
                )
                self.logger.error(
                    f"Problematic note position data: {note.get('position', 'No position data found')}"
                )
