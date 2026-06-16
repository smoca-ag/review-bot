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
from review_bot.backend.gitlab_poster import GitlabReviewPoster

logger = logging.getLogger(__name__)

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

        self._poster = GitlabReviewPoster(
            gitlab_url=self.gitlab_url,
            project_id=self.project_id,
            merge_request_iid=self.merge_request_iid,
            private_token=self.private_token,
            logger=logger,
        )

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
                return [data]

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

            clone_url = project["http_url_to_repo"]

            env = os.environ.copy()
            assert self.private_token is not None
            env["GL_TOKEN"] = self.private_token

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
                        env=env,
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
                            env=env,
                        )

                    subprocess.run(
                        ["git", "checkout", "mr-head"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=repo_dir,
                        env=env,
                    )
                except subprocess.TimeoutExpired as e:
                    self.logger.error(f"Git operation timed out: {e}")
                    raise RuntimeError(f"Git operation timed out: {e}") from e
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"Git operation failed: {e.stderr}")
                    raise RuntimeError(f"Git operation failed: {e.stderr}") from e

            self.repo_dir = repo_dir
        except Exception:
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

    def get_discussion(self) -> Optional[List[Dict[str, Any]]]:
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        return self.get_paginated_response(url)

    def post_line_review(self, text: str, new_path: str, new_position: int) -> None:
        self._poster.post_line_review(
            text=text,
            new_path=new_path,
            new_position=new_position,
            diff_response=self.diff_response,
            discussions=self.discussions,
            versions=self.versions,
            current_user_id=self.current_user_id,
        )

    def post_review(self, text: str) -> None:
        self._poster.post_review(
            text=text,
            discussions=self.discussions,
            current_user_id=self.current_user_id,
        )
