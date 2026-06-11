import base64
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests
from opentelemetry import trace

from review_bot.backend.base_backend import BaseBackend

logger = logging.getLogger(__name__)
from review_bot.text_utils import resolve_diff_coordinates

tracer = trace.get_tracer(__name__)

# Default timeout for HTTP requests (seconds)
REQUEST_TIMEOUT = 30


@dataclass
class GitLabInfo:
    """Parsed information from a GitLab merge request URL."""

    base_url: str
    project_id: str
    merge_request_iid: int


def extract_gitlab_info(url: str) -> GitLabInfo:
    """Extract GitLab instance URL, project path, and MR ID from a GitLab MR URL.

    Args:
        url: Full GitLab merge request URL.

    Returns:
        GitLabInfo with parsed components.

    Raises:
        ValueError: If the URL format is invalid or MR ID cannot be extracted.
    """
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
    mr_id_str: Optional[str] = None
    for i in range(len(path_parts)):
        if path_parts[i] == "merge_requests" and i + 1 < len(path_parts):
            mr_id_str = path_parts[i + 1]
            break

    if mr_id_str is None:
        raise ValueError(
            f"Could not extract merge request ID from URL: {url}. "
            f"Expected URL format: https://gitlab.example.com/group/project/-/merge_requests/19"
        )

    try:
        mr_id = int(mr_id_str)
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid merge request ID '{mr_id_str}' in URL: {url}. Expected a numeric ID."
        )

    return GitLabInfo(
        base_url=f"{protocol}://{host}",
        project_id=quote(project_path, safe=""),
        merge_request_iid=mr_id,
    )


class Gitlab(BaseBackend):
    def __init__(self, logger: logging.Logger, url: str):
        super().__init__(logger, url)
        gitlab_info = extract_gitlab_info(url)
        self.gitlab_url = gitlab_info.base_url
        self.project_id = gitlab_info.project_id
        self.merge_request_iid = gitlab_info.merge_request_iid

        if not self.gitlab_url:
            raise ValueError(
                "Error: GitLab URL must be provided (https://gitlab.example.com/example-group/example-project/-/merge_requests/19)"
            )
        self.private_token = os.getenv("GITLAB_API_TOKEN")
        if not self.private_token:
            raise ValueError("Error: GITLAB_API_TOKEN environment variable is not set")

        # Instance attributes set during load()
        self.current_user_id: Optional[int] = None
        self.versions: List[Dict[str, Any]] = []
        self.discussions: List[Dict[str, Any]] = []
        self.diff_response: str
        self.mr: Optional[Dict[str, Any]] = None

    def load(self) -> None:
        """Load all required data for the merge request."""
        self.current_user_id = self.get_current_user_id()
        self.versions = self.get_versions() or []
        if not self.versions:
            raise RuntimeError("Failed to fetch MR versions. Cannot proceed.")

        self.discussions = self.get_discussion() or []

        diff_response = self.get_merge_request_diff()
        if diff_response is None:
            raise RuntimeError("Failed to fetch MR diff. Cannot proceed.")
        self.diff_response = diff_response

        self.mr = self.get_mr()
        if self.mr is None:
            raise RuntimeError("Failed to fetch MR details. Cannot proceed.")

        self.fetch_repository()

    def get_current_user_id(self) -> Optional[int]:
        user_url = f"{self.gitlab_url}/api/v4/user"
        try:
            user_resp = requests.get(
                user_url,
                headers={"PRIVATE-TOKEN": self.private_token},
                timeout=REQUEST_TIMEOUT,
            )
            user_resp.raise_for_status()
            return user_resp.json().get("id")
        except requests.RequestException as e:
            self.logger.error(f"Could not fetch current user info: {e}")
            return None

    def is_open(self) -> bool:
        if not self.mr:
            return False
        return self.mr.get("state") == "opened"

    def is_draft(self) -> bool:
        if not self.mr:
            return False
        return self.mr.get("work_in_progress", False) or self.mr.get("draft", False)

    def diff(self) -> str:
        return self.diff_response

    def title(self) -> str:
        if not self.mr:
            return ""
        return self.mr.get("title", "")

    def description(self) -> str:
        if not self.mr:
            return ""
        return self.mr.get("description", "")

    def get_versions(self) -> Optional[List[Dict[str, Any]]]:
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/versions"
        result = self.get_json_response(url)
        return result if isinstance(result, list) else None

    def get_json_response(self, url: str) -> Optional[Dict[str, Any]]:
        headers = {"PRIVATE-TOKEN": self.private_token}
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def get_paginated_response(self, url: str) -> List[Dict[str, Any]]:
        headers = {"PRIVATE-TOKEN": self.private_token}
        results: List[Dict[str, Any]] = []
        while url:
            try:
                response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
            except requests.RequestException as e:
                self.logger.error(f"Error fetching {url}: {e}")
                break

            data = response.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                # If it's not a list, pagination might not apply in the expected way
                return [data]  # wrap in list to match return type

            url = response.links.get("next", {}).get("url")
        return results

    def get_text_response(self, url: str) -> Optional[str]:
        headers = {"PRIVATE-TOKEN": self.private_token}
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def get_merge_request_diff(self) -> Optional[str]:
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/raw_diffs"
        return self.get_text_response(url)

    def get_mr(self) -> Optional[Dict[str, Any]]:
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}"
        return self.get_json_response(url)

    def get_project(self) -> Optional[Dict[str, Any]]:
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}"
        return self.get_json_response(url)

    def fetch_repository(self) -> None:
        repo_dir = tempfile.mkdtemp()

        try:
            project = self.get_project()
            if not project or "http_url_to_repo" not in project:
                self.logger.error("Could not get project details for cloning.")
                return

            # Keep the remote URL completely clean
            clone_url = project["http_url_to_repo"]

            # 1. Pass the token securely as an isolated environment variable
            env = os.environ.copy()
            env["GL_TOKEN"] = self.private_token

            # 2. Inject the custom credential helper via the Git environment block
            # This allows both regular Git and Git LFS to access the token in-memory
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "credential.helper"
            env["GIT_CONFIG_VALUE_0"] = (
                '!f() { echo "username=oauth2"; echo "password=$GL_TOKEN"; }; f'
            )

            with tracer.start_as_current_span("project_checkout") as span:
                span.set_attribute("gitlab.project_id", self.project_id)
                span.set_attribute("gitlab.merge_request_iid", self.merge_request_iid)
                span.set_attribute("gitlab.repo_dir", repo_dir)

                try:
                    subprocess.run(
                        ["git", "init", repo_dir],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    subprocess.run(
                        ["git", "remote", "add", "origin", clone_url],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=repo_dir,
                    )

                    # 3. Pass the custom env dictionary to network operations
                    subprocess.run(
                        [
                            "git",
                            "fetch",
                            "--depth",
                            "1",
                            "origin",
                            f"refs/merge-requests/{self.merge_request_iid}/head:mr-head",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=repo_dir,
                        env=env,  # Git reads the auth helper here
                    )

                    target_branch = self.mr.get("target_branch") if self.mr else None
                    if target_branch:
                        subprocess.run(
                            [
                                "git",
                                "fetch",
                                "--depth",
                                "1",
                                "origin",
                                f"refs/heads/{target_branch}:target-branch",
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=120,
                            cwd=repo_dir,
                            env=env,  # Git reads the auth helper here
                        )

                    # 4. CRITICAL FOR LFS: Pass the env to checkout!
                    # This is when Git LFS executes the smudge filter to download large files.
                    subprocess.run(
                        ["git", "checkout", "mr-head"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=120,  # Bumped timeout slightly; LFS downloads take longer
                        cwd=repo_dir,
                        env=env,  # <--- Git LFS hooks read the auth helper right here
                    )
                except subprocess.TimeoutExpired as e:
                    self.logger.error(f"Git operation timed out: {e}")
                    raise RuntimeError(f"Git operation timed out: {e}") from e
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"Git operation failed: {e.stderr}")
                    raise RuntimeError(f"Git operation failed: {e.stderr}") from e

            # Only assign repo_dir after all git operations succeed
            self.repo_dir = repo_dir
        except Exception:
            # Clean up temp directory on failure
            try:
                shutil.rmtree(repo_dir)
            except Exception as e:
                self.logger.error(f"Failed to clean up temp repo directory: {e}")
            raise

    def cleanup(self) -> None:
        if self.repo_dir:
            try:
                shutil.rmtree(self.repo_dir)
                self.logger.info(f"Cleaned up repo directory: {self.repo_dir}")
            except Exception as e:
                self.logger.error(f"Failed to clean up repo directory: {e}")
            finally:
                self.repo_dir = None

        super().cleanup()

    def get_discussion(self) -> Optional[List[Dict[str, Any]]]:
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        return self.get_paginated_response(url)

    def post_line_review(self, text: str, new_path: str, new_position: int) -> None:
        if new_path == "/dev/null" or not new_path:
            return  # Can't review a completely deleted file

        new_path = new_path.lstrip("/")

        old_path, old_position = resolve_diff_coordinates(
            self.diff_response, new_path, new_position
        )

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

        # Guard against None/empty versions
        if not self.versions:
            self.logger.error("No versions available for posting review.")
            return

        version = self.versions[0]
        # Build position mapping payload safely
        position = {
            "new_path": new_path,
            "old_path": old_path,
            "base_sha": version.get("base_commit_sha"),
            "start_sha": version.get("start_commit_sha"),
            "head_sha": version.get("head_commit_sha"),
            "position_type": "text",
            "new_line": new_position,
            "old_line": old_position,
        }

        # Clean out any keys containing None (e.g., old_line on an added line)
        position = {k: v for k, v in position.items() if v is not None}

        payload = {"body": text, "position": position}

        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as e:
            self.logger.error(f"Error posting inline discussion note to GitLab: {e}")

    def post_review(self, text: str) -> None:
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }

        current_user_id = self.current_user_id
        if not current_user_id:
            # Fallback if load() didn't get it
            try:
                user_url = f"{self.gitlab_url}/api/v4/user"
                user_resp = requests.get(
                    user_url,
                    headers={"PRIVATE-TOKEN": self.private_token},
                    timeout=REQUEST_TIMEOUT,
                )
                user_resp.raise_for_status()
                current_user_id = user_resp.json().get("id")
            except requests.RequestException as e:
                self.logger.error(f"Could not fetch current user info: {e}")
                return

        # 2. Get existing notes
        notes_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/notes"

        existing_notes = []
        for discussion in self.discussions:
            for note in discussion.get("notes", []):
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
            try:
                update_resp = requests.put(
                    update_url,
                    headers=headers,
                    json={"body": text},
                    timeout=REQUEST_TIMEOUT,
                )
                update_resp.raise_for_status()
                self.logger.info("Successfully updated existing general MR note.")
            except requests.RequestException as e:
                self.logger.error(f"Error updating general MR note: {e}")

            # Delete the rest
            for note in existing_notes[1:]:
                delete_url = f"{notes_url}/{note['id']}"
                try:
                    del_resp = requests.delete(
                        delete_url, headers=headers, timeout=REQUEST_TIMEOUT
                    )
                    del_resp.raise_for_status()
                except requests.RequestException as e:
                    self.logger.error(f"Error deleting old general MR note: {e}")
        else:
            # Post new
            payload = {"body": text}
            try:
                response = requests.post(
                    notes_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                self.logger.info("Successfully posted new general MR note.")
            except requests.RequestException as e:
                self.logger.error(f"Error posting general MR note to GitLab: {e}")
