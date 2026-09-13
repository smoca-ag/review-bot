import logging
import unittest
from unittest import mock

import requests as requests_lib

from review_bot.backend.gitlab_poster import GitlabReviewPoster, _newest_version
from review_bot.utils.diff import diff_line_mapping, resolve_diff_coordinates

DIFF_TEXT = """diff --git a/app.rb b/app.rb
--- a/app.rb
+++ b/app.rb
@@ -1,4 +1,5 @@
 line1
+added2
 line3
-line4
+new4
 line5
diff --git a/other.rb b/other.rb
--- a/other.rb
+++ b/other.rb
@@ -1,1 +1,2 @@
 only
+added
"""

# Blank context line serialized without its leading space, as GitLab does
# for empty lines inside hunks.
DIFF_TEXT_BLANK_CTX = """diff --git a/app.rb b/app.rb
--- a/app.rb
+++ b/app.rb
@@ -1,3 +1,4 @@
 line1
+added2

 line3
"""


def _version(id_: int, created_at: str, head: str) -> dict:
    return {
        "id": id_,
        "created_at": created_at,
        "base_commit_sha": "base",
        "start_commit_sha": "start",
        "head_commit_sha": head,
    }


def _fake_response(json_data=None, text=""):
    resp = mock.Mock()
    resp.json.return_value = json_data
    resp.text = text
    resp.raise_for_status.return_value = None
    return resp


class TestNewestVersion(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(_newest_version([]))

    def test_newest_first_ordering(self):
        versions = [
            _version(3, "2026-01-03T00:00:00Z", "c"),
            _version(1, "2026-01-01T00:00:00Z", "a"),
        ]
        newest = _newest_version(versions)
        if newest is None:
            self.fail("expected a newest version")
        self.assertEqual(newest["head_commit_sha"], "c")

    def test_oldest_first_ordering(self):
        versions = [
            _version(1, "2026-01-01T00:00:00Z", "a"),
            _version(3, "2026-01-03T00:00:00Z", "c"),
        ]
        newest = _newest_version(versions)
        if newest is None:
            self.fail("expected a newest version")
        self.assertEqual(newest["head_commit_sha"], "c")


class TestDiffLineMapping(unittest.TestCase):
    def test_added_line(self):
        self.assertEqual(diff_line_mapping(DIFF_TEXT, "app.rb", 2), (True, None))

    def test_context_line(self):
        self.assertEqual(diff_line_mapping(DIFF_TEXT, "app.rb", 3), (True, 2))
        self.assertEqual(diff_line_mapping(DIFF_TEXT, "app.rb", 5), (True, 4))

    def test_line_outside_hunks(self):
        self.assertEqual(diff_line_mapping(DIFF_TEXT, "app.rb", 99), (False, None))

    def test_unknown_file(self):
        self.assertEqual(diff_line_mapping(DIFF_TEXT, "missing.rb", 1), (False, None))

    def test_second_file_section(self):
        self.assertEqual(diff_line_mapping(DIFF_TEXT, "other.rb", 2), (True, None))

    def test_no_diff(self):
        self.assertEqual(diff_line_mapping(None, "app.rb", 1), (False, None))

    def test_blank_context_line_without_leading_space(self):
        self.assertEqual(diff_line_mapping(DIFF_TEXT_BLANK_CTX, "app.rb", 2), (True, None))
        self.assertEqual(diff_line_mapping(DIFF_TEXT_BLANK_CTX, "app.rb", 3), (True, 2))
        self.assertEqual(diff_line_mapping(DIFF_TEXT_BLANK_CTX, "app.rb", 4), (True, 3))
        self.assertEqual(
            resolve_diff_coordinates(DIFF_TEXT_BLANK_CTX, "app.rb", 3), ("app.rb", 2)
        )


class TestHeadShaCaching(unittest.TestCase):
    def setUp(self):
        self.poster = GitlabReviewPoster(
            "https://gitlab.example", "grp%2Fproj", 1, "tok", logging.getLogger()
        )
        self.loaded_versions = [
            _version(2, "2026-01-02T00:00:00Z", "head2"),
            _version(1, "2026-01-01T00:00:00Z", "head1"),
        ]

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_transient_failure_is_retried_on_next_call(self, requests):
        """One failed fetch must not suppress inline comments for the run."""
        requests.RequestException = requests_lib.RequestException
        requests.get.side_effect = [
            requests_lib.RequestException("boom"),
            _fake_response(json_data=self.loaded_versions),
        ]
        self.assertIsNone(self.poster.get_current_head_sha())
        self.assertEqual(self.poster.get_current_head_sha(), "head2")
        self.assertEqual(requests.get.call_count, 2)

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_success_is_cached(self, requests):
        requests.get.return_value = _fake_response(json_data=self.loaded_versions)
        self.assertEqual(self.poster.get_current_head_sha(), "head2")
        self.assertEqual(self.poster.get_current_head_sha(), "head2")
        self.assertEqual(requests.get.call_count, 1)


class TestPostLineReview(unittest.TestCase):
    def setUp(self):
        self.poster = GitlabReviewPoster(
            "https://gitlab.example", "grp%2Fproj", 1, "tok", logging.getLogger()
        )
        self.loaded_versions = [
            _version(2, "2026-01-02T00:00:00Z", "head2"),
            _version(1, "2026-01-01T00:00:00Z", "head1"),
        ]

    def _post_line(self, patched, diff_text=DIFF_TEXT, new_line=2):
        patched.post_line_review(
            text="**MAJOR (logic)**: issue",
            new_path="app.rb",
            new_position=new_line,
            diff_response=diff_text,
            discussions=[],
            versions=self.loaded_versions,
            current_user_id=7,
        )

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_stale_head_skips_post(self, requests):
        requests.get.return_value = _fake_response(
            json_data=[_version(3, "2026-01-03T00:00:00Z", "head3")]
        )
        self._post_line(self.poster)
        requests.post.assert_not_called()

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_failed_head_fetch_skips_post(self, requests):
        requests.RequestException = requests_lib.RequestException
        requests.get.side_effect = requests_lib.RequestException("boom")
        self._post_line(self.poster)
        requests.post.assert_not_called()

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_line_not_in_diff_skips_post(self, requests):
        requests.get.return_value = _fake_response(json_data=self.loaded_versions)
        self._post_line(self.poster, new_line=42)
        requests.post.assert_not_called()

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_empty_text_skips_post_without_api_call(self, requests):
        self.poster.logger = mock.Mock()
        self.poster.post_line_review(
            text="   ",
            new_path="app.rb",
            new_position=2,
            diff_response=DIFF_TEXT,
            discussions=[],
            versions=self.loaded_versions,
            current_user_id=7,
        )
        requests.get.assert_not_called()
        requests.post.assert_not_called()

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_valid_comment_posts_with_newest_version(self, requests):
        requests.get.return_value = _fake_response(json_data=self.loaded_versions)
        requests.post.return_value = _fake_response()
        self._post_line(self.poster)
        requests.post.assert_called_once()
        payload = requests.post.call_args.kwargs["json"]
        self.assertEqual(payload["position"]["head_sha"], "head2")
        self.assertEqual(payload["position"]["new_line"], 2)

    def _dup_discussion(self, head_sha):
        return {
            "id": "disc-dup",
            "notes": [
                {
                    "id": 99,
                    "type": "DiffNote",
                    "resolved": False,
                    "author": {"id": 7},
                    "position": {
                        "new_path": "app.rb",
                        "new_line": 2,
                        "head_sha": head_sha,
                    },
                }
            ],
        }

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_existing_note_at_current_head_blocks_post(self, requests):
        requests.get.return_value = _fake_response(json_data=self.loaded_versions)
        self.poster.post_line_review(
            text="**MAJOR (logic)**: issue",
            new_path="app.rb",
            new_position=2,
            diff_response=DIFF_TEXT,
            discussions=[self._dup_discussion("head2")],
            versions=self.loaded_versions,
            current_user_id=7,
        )
        requests.post.assert_not_called()

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_outdated_note_at_same_position_does_not_block_post(self, requests):
        requests.get.return_value = _fake_response(json_data=self.loaded_versions)
        requests.post.return_value = _fake_response()
        self.poster.post_line_review(
            text="**MAJOR (logic)**: issue",
            new_path="app.rb",
            new_position=2,
            diff_response=DIFF_TEXT,
            discussions=[self._dup_discussion("head1")],
            versions=self.loaded_versions,
            current_user_id=7,
        )
        requests.post.assert_called_once()


class TestCleanupGhostNotes(unittest.TestCase):
    HEAD = "H"

    def setUp(self):
        self.poster = GitlabReviewPoster(
            "https://gitlab.example", "grp%2Fproj", 1, "tok", logging.getLogger()
        )

    def _note(self, id_, head_sha, new_line, old_line=None, author_id=7, resolved=False):
        position = {"new_path": "app.rb", "new_line": new_line, "head_sha": head_sha}
        if old_line is not None:
            position["old_line"] = old_line
        return {
            "id": f"disc-{id_}",
            "notes": [
                {
                    "id": id_,
                    "type": "DiffNote",
                    "resolved": resolved,
                    "author": {"id": author_id},
                    "position": position,
                }
            ],
        }

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_deletes_only_unrenderable_bot_notes(self, requests):
        def get_router(url, *args, **kwargs):
            if url.endswith("/raw_diffs"):
                return _fake_response(text=DIFF_TEXT)
            raise AssertionError(f"unexpected GET {url}")

        requests.get.side_effect = get_router
        requests.delete.return_value = _fake_response()

        discussions = [
            self._note(1, head_sha="OLD", new_line=3, old_line=2),  # outdated but renders
            self._note(2, head_sha=self.HEAD, new_line=99),  # not in diff
            self._note(3, head_sha=self.HEAD, new_line=3, old_line=2),  # valid context
            self._note(4, head_sha=self.HEAD, new_line=2),  # valid added line
            self._note(5, head_sha=self.HEAD, new_line=99, resolved=True),  # resolved
            self._note(6, head_sha="OLD", new_line=99, author_id=8),  # other author
            self._note(7, head_sha="OLD", new_line=99),  # outdated and unrenderable
        ]

        self.poster.cleanup_ghost_notes(discussions, current_user_id=7)

        deleted_ids = [c.args[0].rstrip("/").split("/")[-1] for c in requests.delete.call_args_list]
        self.assertEqual(sorted(deleted_ids), ["2", "7"])

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_no_cleanup_without_user_id(self, requests):
        self.poster.cleanup_ghost_notes([self._note(1, "OLD", 99)], current_user_id=None)
        requests.get.assert_not_called()
        requests.delete.assert_not_called()


class TestPostGeneralNote(unittest.TestCase):
    def setUp(self):
        self.poster = GitlabReviewPoster(
            "https://gitlab.example", "grp%2Fproj", 1, "tok", logging.getLogger()
        )
        self.discussions = [
            {
                "notes": [
                    {"id": 10, "system": False, "author": {"id": 7}, "body": "old"},
                    {"id": 11, "system": False, "author": {"id": 7}, "body": "older"},
                ]
            }
        ]

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_failed_update_posts_fresh_note_without_deleting(self, requests):
        requests.RequestException = requests_lib.RequestException
        requests.get.return_value = _fake_response(text=DIFF_TEXT)
        requests.put.side_effect = requests_lib.RequestException("boom")
        requests.post.return_value = _fake_response()

        self.poster.post_review("new review", self.discussions, current_user_id=7)

        self.assertEqual(requests.put.call_count, 1)
        requests.delete.assert_not_called()
        self.assertEqual(requests.post.call_count, 1)
        self.assertTrue(requests.post.call_args.args[0].endswith("/notes"))
        self.assertEqual(
            requests.post.call_args.kwargs["json"], {"body": "new review"}
        )

    @mock.patch("review_bot.backend.gitlab_poster.requests")
    def test_successful_update_deletes_extras_without_posting(self, requests):
        requests.RequestException = requests_lib.RequestException
        requests.get.return_value = _fake_response(text=DIFF_TEXT)
        requests.put.return_value = _fake_response()
        requests.delete.return_value = _fake_response()

        self.poster.post_review("new review", self.discussions, current_user_id=7)

        self.assertEqual(requests.delete.call_count, 1)
        deleted_id = requests.delete.call_args.args[0].rstrip("/").split("/")[-1]
        self.assertEqual(deleted_id, "11")
        requests.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
