import logging
from typing import Any

import requests

from review_bot.utils.diff import diff_line_mapping, resolve_diff_coordinates

REQUEST_TIMEOUT = 30


def _newest_version(
    versions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the newest diff version regardless of the API's list ordering.

    Args:
        versions: Diff version payloads as returned by the GitLab API.

    Returns:
        The version with the highest created_at/id, or None if empty.
    """
    if not versions:
        return None
    return max(versions, key=lambda v: (v.get("created_at") or "", v.get("id") or 0))


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
        self._current_head_sha: str | None = None
        self._head_sha_fetched = False

    def get_current_head_sha(self) -> str | None:
        """Fetch (and cache per review run) the MR's current head sha.

        Returns:
            Head sha of the newest diff version, or None if it could not be
            determined.
        """
        if not self._head_sha_fetched:
            self._head_sha_fetched = True
            url = (
                f"{self.gitlab_url}/api/v4/projects/{self.project_id}"
                f"/merge_requests/{self.merge_request_iid}/versions"
            )
            try:
                response = requests.get(
                    url,
                    headers={"PRIVATE-TOKEN": self.private_token},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                versions = response.json()
                newest = _newest_version(versions if isinstance(versions, list) else [])
                self._current_head_sha = (
                    newest.get("head_commit_sha") if newest else None
                )
            except requests.RequestException as e:
                self.logger.error(
                    f"Could not fetch MR versions at post time: {e}"
                )
        return self._current_head_sha

    def _head_matches_review_snapshot(
        self, versions: list[dict[str, Any]]
    ) -> bool:
        """Check that the MR head has not moved since the review started.

        Args:
            versions: Diff versions captured at review load time, the same
                snapshot the diff and line coordinates were computed from.

        Returns:
            True if the MR's current head still matches the snapshot. False
            means inline comments must not be posted: their positions may no
            longer exist in the MR's latest diff, which would make them
            invisible and unresolvable ghost notes.
        """
        loaded = _newest_version(versions)
        fresh_head = self.get_current_head_sha()
        if loaded is None or fresh_head is None:
            self.logger.error(
                "Could not determine MR head at post time; skipping inline comment."
            )
            return False
        if loaded.get("head_commit_sha") != fresh_head:
            self.logger.warning(
                f"MR head changed during review "
                f"({loaded.get('head_commit_sha')} -> {fresh_head}); "
                "skipping inline comment to avoid ghost notes."
            )
            return False
        return True

    def post_line_review(
        self,
        text: str,
        new_path: str,
        new_position: int,
        diff_response: str,
        discussions: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        current_user_id: int | None,
    ) -> None:
        if new_path == "/dev/null" or not new_path:
            return

        if not text or not text.strip():
            self.logger.warning(
                f"Empty comment text for {new_path}:{new_position}; skipping post."
            )
            return

        new_path = new_path.lstrip("/")

        if not self._head_matches_review_snapshot(versions):
            return

        in_diff, _ = diff_line_mapping(diff_response, new_path, new_position)
        if not in_diff:
            self.logger.warning(
                f"{new_path}:{new_position} is not part of the review's diff snapshot; "
                "skipping inline comment to avoid an unrenderable note."
            )
            return

        old_path, old_position = resolve_diff_coordinates(
            diff_response, new_path, new_position
        )

        def get_pos(note):
            pos = note.get("position")
            return pos if pos is not None else {}

        # Only notes on the current head count as duplicates: notes pinned to
        # an older head may be swept or stay "outdated", so the fresh finding
        # must still be posted.
        fresh_head = self.get_current_head_sha()
        if any(
            get_pos(note).get("new_path") == new_path
            and get_pos(note).get("new_line") == new_position
            and get_pos(note).get("head_sha") == fresh_head
            and note.get("author", {}).get("id") == current_user_id
            for d in discussions
            if d.get("notes")
            for note in d["notes"]
        ):
            self.logger.info(
                f"Already a discussion by the bot on path {new_path} and position {new_position}"
            )
            return

        version = _newest_version(versions)
        if version is None:
            self.logger.error("No versions available for posting review.")
            return

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
        discussions: list[dict[str, Any]],
        current_user_id: int | None,
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

        self.cleanup_ghost_notes(discussions, current_user_id)

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

    def cleanup_ghost_notes(
        self,
        discussions: list[dict[str, Any]],
        current_user_id: int | None,
    ) -> None:
        """Delete unresolved inline bot notes that GitLab can no longer render.

        A DiffNote whose position does not map to the MR's current diff is
        invisible in the GitLab UI and can neither be resolved nor deleted
        there; only this API call can remove it. Such notes are produced when
        a review posts against a head that moved mid-review. Notes that still
        render (including outdated ones pinned to an older head), resolved
        threads, and notes by other authors are left untouched.

        Args:
            discussions: Raw discussion payloads as loaded for this review.
            current_user_id: GitLab user id of the bot account.
        """
        if current_user_id is None:
            return

        diff_url = (
            f"{self.gitlab_url}/api/v4/projects/{self.project_id}"
            f"/merge_requests/{self.merge_request_iid}/raw_diffs"
        )
        try:
            diff_resp = requests.get(
                diff_url,
                headers={"PRIVATE-TOKEN": self.private_token},
                timeout=REQUEST_TIMEOUT,
            )
            diff_resp.raise_for_status()
            diff_text = diff_resp.text
        except requests.RequestException as e:
            self.logger.error(
                f"Could not fetch current diff for ghost-note cleanup: {e}"
            )
            return

        discussions_url = (
            f"{self.gitlab_url}/api/v4/projects/{self.project_id}"
            f"/merge_requests/{self.merge_request_iid}/discussions"
        )
        headers = {"PRIVATE-TOKEN": self.private_token}

        for discussion in discussions:
            for note in discussion.get("notes", []):
                if note.get("type") != "DiffNote" or note.get("resolved"):
                    continue
                if note.get("author", {}).get("id") != current_user_id:
                    continue
                position = note.get("position") or {}
                new_path = (position.get("new_path") or "").lstrip("/")
                new_line = position.get("new_line")
                if not new_path or new_line is None:
                    continue
                in_diff, old_mapped = diff_line_mapping(
                    diff_text, new_path, new_line
                )
                renderable = in_diff and old_mapped == position.get("old_line")
                if renderable:
                    continue
                delete_url = f"{discussions_url}/{discussion['id']}/notes/{note['id']}"
                try:
                    del_resp = requests.delete(
                        delete_url, headers=headers, timeout=REQUEST_TIMEOUT
                    )
                    del_resp.raise_for_status()
                    self.logger.info(
                        f"Deleted unrenderable inline note {note['id']} "
                        f"on {new_path}:{new_line}"
                    )
                except requests.RequestException as e:
                    self.logger.error(
                        f"Error deleting unrenderable inline note {note['id']}: {e}"
                    )
