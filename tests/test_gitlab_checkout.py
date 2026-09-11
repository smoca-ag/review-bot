"""Unit tests for Gitlab.fetch_repository checkout behavior (mocked subprocess)."""

import logging
import subprocess
import unittest
from unittest import mock

from review_bot.backend.gitlab import Gitlab


def _ok(cmd) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


class TestFetchRepository(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("gitlab_checkout_test")
        self.logger.addHandler(logging.NullHandler())
        with mock.patch.dict("os.environ", {"GITLAB_API_TOKEN": "test-token"}):
            self.backend = Gitlab(
                self.logger,
                "https://gitlab.example.com/group/project/-/merge_requests/1",
            )
        self.backend.mr = {"target_branch": "main"}

    def tearDown(self):
        self.backend.cleanup()

    def _fetch(self, fake_run):
        with mock.patch.object(
            self.backend,
            "get_project",
            return_value={"http_url_to_repo": "https://gitlab.example.com/g/p.git"},
        ):
            with mock.patch(
                "review_bot.backend.gitlab.subprocess.run", side_effect=fake_run
            ) as run_mock:
                self.backend.fetch_repository()
        return [c.args[0] for c in run_mock.call_args_list]

    def test_fetch_depth_and_submodule_init(self):
        recorded = []

        def fake_run(cmd, **kwargs):
            recorded.append(cmd)
            return _ok(cmd)

        with mock.patch(
            "review_bot.backend.gitlab.shutil.which", return_value=None
        ):
            cmds = self._fetch(fake_run)

        fetches = [c for c in cmds if c[:2] == ["git", "fetch"]]
        self.assertTrue(fetches)
        for fetch in fetches:
            self.assertIn("50", fetch)
            self.assertNotIn("1", [str(a) for a in fetch[2:4]])

        self.assertTrue(
            any(
                c[:2] == ["git", "submodule"] and "--init" in c and "--recursive" in c
                for c in cmds
            )
        )
        self.assertFalse(any("lfs" in c for c in cmds))
        self.assertIsNotNone(self.backend.repo_dir)

    def test_lfs_pull_when_git_lfs_available(self):
        def fake_run(cmd, **kwargs):
            return _ok(cmd)

        with mock.patch(
            "review_bot.backend.gitlab.shutil.which",
            return_value="/usr/bin/git-lfs",
        ):
            cmds = self._fetch(fake_run)

        self.assertTrue(any(c[:2] == ["git", "lfs"] and "pull" in c for c in cmds))

    def test_submodule_failure_is_warn_only(self):
        def fake_run(cmd, **kwargs):
            if "submodule" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr="nope")
            return _ok(cmd)

        with mock.patch(
            "review_bot.backend.gitlab.shutil.which", return_value=None
        ):
            cmds = self._fetch(fake_run)

        self.assertIsNotNone(self.backend.repo_dir)


if __name__ == "__main__":
    unittest.main()
