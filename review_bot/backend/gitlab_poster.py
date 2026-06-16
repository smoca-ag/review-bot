import logging
from typing import Any, Dict, List, Optional

import requests

from review_bot.text_utils import resolve_diff_coordinates

REQUEST_TIMEOUT = 30


class GitlabReviewPoster:
    """Posts review comments to a GitLab merge request via the API.

    Independent of container management, diff loading, and repo checkout.
    """

    def __init__(
        self,
        gitlab_url: str,
        project_id: str,
        merge_request_iid: int,
        private_token: str,
        logger: logging.Logger,
    ) -> None:
        self.gitlab_url = gitlab_url
        self.project_id = project_id
        self.merge_request_iid = merge_request_iid
        self.private_token = private_token
        self.logger = logger

    def post_line_review(
        self,
        text: str,
        new_path: str,
        new_position: int,
        diff_response: str,
        discussions: List[Dict[str, Any]],
        versions: List[Dict[str, Any]],
        current_user_id: Optional[int],
    ) -> None:
        if new_path == "/dev/null" or not new_path:
            return

        new_path = new_path.lstrip("/")

        old_path, old_position = resolve_diff_coordinates(
            diff_response, new_path, new_position
        )

        def get_pos(note):
            pos = note.get("position")
            return pos if pos is not None else {}

        if any(
            get_pos(note).get("new_path") == new_path
            and get_pos(note).get("new_line") == new_position
            and note.get("author", {}).get("id") == current_user_id
            for d in discussions
            if d.get("notes")
            for note in d["notes"]
        ):
            self.logger.info(
                f"Already a discussion by the bot on path {new_path} and position {new_position}"
            )
            return

        if not versions:
            self.logger.error("No versions available for posting review.")
            return

        version = versions[-1]
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

    def post_review(
        self,
        text: str,
        discussions: List[Dict[str, Any]],
        current_user_id: Optional[int],
    ) -> None:
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json",
        }

        if not current_user_id:
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

        notes_url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/notes"

        existing_notes = []
        for discussion in discussions:
            for note in discussion.get("notes", []):
                if (
                    not note.get("system")
                    and note.get("author", {}).get("id") == current_user_id
                ):
                    if note.get("type") != "DiffNote":
                        existing_notes.append(note)

        if existing_notes:
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
            payload = {"body": text}
            try:
                response = requests.post(
                    notes_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                self.logger.info("Successfully posted new general MR note.")
            except requests.RequestException as e:
                self.logger.error(f"Error posting general MR note to GitLab: {e}")
