"""Unit tests for ContainerManager restart behavior and brace expansion."""

import logging
import os
import subprocess
import unittest
from unittest import mock

from review_bot.backend.container_manager import (
    SANDBOX_UNAVAILABLE_MESSAGE,
    ContainerManager,
    _owner_pid,
    expand_braces,
    prune_stale_containers,
)


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


class TestExpandBraces(unittest.TestCase):
    def test_simple_alternation(self):
        self.assertEqual(
            expand_braces("**/*.{test,spec}.ts"),
            ["**/*.test.ts", "**/*.spec.ts"],
        )

    def test_sequential_groups(self):
        self.assertEqual(
            expand_braces("app/{a,b}/{c,d}.py"),
            ["app/a/c.py", "app/a/d.py", "app/b/c.py", "app/b/d.py"],
        )

    def test_nested_group_covers_all_alternatives(self):
        expanded = expand_braces("go{1,{2,3}}")
        for expected in ("go1", "go2", "go3"):
            self.assertIn(expected, expanded)

    def test_group_without_comma_stays_literal(self):
        self.assertEqual(expand_braces("{a}"), ["{a}"])
        self.assertEqual(expand_braces("Cargo{one}"), ["Cargo{one}"])

    def test_pattern_without_braces_unchanged(self):
        self.assertEqual(expand_braces("src/*.py"), ["src/*.py"])

    def test_pathological_expansion_refused(self):
        pattern = "x{a,b}{a,b}{a,b}{a,b}{a,b}{a,b}"
        self.assertEqual(expand_braces(pattern), [pattern])


class TestContainerManagerRestart(unittest.TestCase):
    def setUp(self):
        logging.getLogger("container_manager_test").addHandler(logging.NullHandler())
        self.mgr = ContainerManager(logging.getLogger("container_manager_test"))
        self.mgr.container_name = "review-bot-test"
        self.mgr.repo_dir = "/tmp/repo"
        self.mgr.image = "review-bot-env:latest"

    def test_execute_restarts_container_once(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1] == "exec":
                if cmd[-1] == "true":
                    return _ok()
                if cmd[2] == "review-bot-test":
                    raise subprocess.CalledProcessError(
                        125,
                        cmd,
                        output='Error: no container with name or ID "review-bot-test" found',
                    )
                return _ok("ok")
            if cmd[1] == "ps":
                return _ok("")
            if cmd[1] == "run":
                return _ok("container-id")
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ):
            result = self.mgr.execute_command("ls")

        self.assertEqual(result, "ok")
        self.assertTrue(any(cmd[1] == "run" for cmd in calls))
        self.assertTrue(any(cmd[1] == "ps" for cmd in calls))
        self.assertEqual(sum(1 for cmd in calls if cmd[1] == "run"), 1)

    def test_execute_no_restart_on_normal_failure(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1] == "exec":
                raise subprocess.CalledProcessError(1, cmd, output="boom")
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ):
            result = self.mgr.execute_command("ls")

        self.assertTrue(result.startswith("Command failed with exit code 1"))
        self.assertEqual(len(calls), 1)

    def test_execute_returns_unavailable_message_when_restart_fails(self):
        def fake_run(cmd, **kwargs):
            if cmd[1] == "exec":
                raise subprocess.CalledProcessError(
                    125,
                    cmd,
                    output="no container with name or ID found",
                )
            if cmd[1] == "ps":
                return _ok("")
            if cmd[1] == "run":
                return _ok("", returncode=1)
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ):
            result = self.mgr.execute_command("ls")

        self.assertEqual(result, SANDBOX_UNAVAILABLE_MESSAGE)

    def test_no_container_name_short_circuits(self):
        self.mgr.container_name = None
        self.assertEqual(
            self.mgr.execute_command("ls"), "Error: No active container found."
        )

    def test_get_file_raw_returns_none_for_missing_file(self):
        def fake_run(cmd, **kwargs):
            return _ok(
                "cat: /workspace/foo: No such file or directory", returncode=1
            )

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ):
            self.assertIsNone(self.mgr.get_file_raw("/workspace/foo"))

    def test_glob_files_expands_braces_in_argv(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _ok("a.test.ts\nb.spec.ts")

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ):
            result = self.mgr.glob_files("**/*.{test,spec}.ts")

        self.assertIn("a.test.ts", result)
        self.assertEqual(
            captured["cmd"][-2:], ["**/*.test.ts", "**/*.spec.ts"]
        )


class TestContainerManagerSetup(unittest.TestCase):
    def test_setup_uses_overlay_mount_and_resource_limits(self):
        logging.getLogger("container_manager_test").addHandler(logging.NullHandler())
        mgr = ContainerManager(logging.getLogger("container_manager_test"))
        run_cmds = []

        def fake_run(cmd, **kwargs):
            if cmd[1] == "build":
                return _ok()
            if cmd[1] == "run":
                run_cmds.append(cmd)
                return _ok("container-id")
            if cmd[1] == "exec" and cmd[-1] == "true":
                return _ok()
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ):
            mgr.setup("/tmp/repo", image="review-bot-env:latest")

        assert mgr.container_name is not None
        self.assertRegex(mgr.container_name, r"^review-bot-p\d+-[0-9a-f]{8}$")
        self.assertEqual(_owner_pid(mgr.container_name), os.getpid())
        run_cmd = run_cmds[0]
        mounts = [a for a in run_cmd if a.endswith(":/workspace:O")]
        self.assertEqual(len(mounts), 1)
        for flag in ("--cpus=4", "--memory=8g", "--memory-swap=8g", "--pids-limit=8192"):
            self.assertIn(flag, run_cmd)

    def test_setup_raises_when_health_check_fails(self):
        logging.getLogger("container_manager_test").addHandler(logging.NullHandler())
        mgr = ContainerManager(logging.getLogger("container_manager_test"))

        def fake_run(cmd, **kwargs):
            if cmd[1] == "build":
                return _ok()
            if cmd[1] == "run":
                return _ok("container-id")
            if cmd[1] == "exec":
                return _ok("", returncode=1)
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ), mock.patch("review_bot.backend.container_manager.time.sleep"):
            with self.assertRaises(RuntimeError):
                mgr.setup("/tmp/repo", image="review-bot-env:latest")


class TestPruneStaleContainers(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("prune_test")
        self.logger.addHandler(logging.NullHandler())

    def _prune(self, names: str, alive_pids: set[int], ps_rc: int = 0):
        removed: list[str] = []

        def fake_run(cmd, **kwargs):
            if cmd[1] == "ps":
                return _ok(names, returncode=ps_rc)
            if cmd[1] == "rm":
                removed.append(cmd[-1])
                return _ok(cmd[-1])
            raise AssertionError(f"unexpected command: {cmd}")

        def fake_kill(pid: int, sig: int) -> None:
            if pid not in alive_pids:
                raise ProcessLookupError()

        with mock.patch(
            "review_bot.backend.container_manager.subprocess.run",
            side_effect=fake_run,
        ), mock.patch(
            "review_bot.backend.container_manager.os.kill", side_effect=fake_kill
        ):
            count = prune_stale_containers(self.logger)
        return count, removed

    def test_removes_containers_of_dead_processes(self):
        dead = "review-bot-p999999-abcd1234"
        alive = f"review-bot-p{os.getpid()}-1234abcd"
        count, removed = self._prune(f"{dead}\n{alive}\n", alive_pids={os.getpid()})
        self.assertEqual(count, 1)
        self.assertEqual(removed, [dead])

    def test_keeps_containers_of_live_processes(self):
        alive = f"review-bot-p{os.getpid()}-1234abcd"
        count, removed = self._prune(f"{alive}\n", alive_pids={os.getpid()})
        self.assertEqual((count, removed), (0, []))

    def test_ignores_foreign_container_names(self):
        count, removed = self._prune("review-bot-old\nother-thing\n", alive_pids=set())
        self.assertEqual((count, removed), (0, []))

    def test_list_failure_is_not_fatal(self):
        count, removed = self._prune("", alive_pids=set(), ps_rc=125)
        self.assertEqual((count, removed), (0, []))

    def test_owner_pid_parsing(self):
        self.assertEqual(_owner_pid("review-bot-p42-deadbeef"), 42)
        self.assertIsNone(_owner_pid("review-bot-deadbee1"))
        self.assertIsNone(_owner_pid("review-bot-pX-deadbee1"))


if __name__ == "__main__":
    unittest.main()
