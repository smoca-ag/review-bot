"""Tests for ReviewManager worker resilience against process-start failures."""

import multiprocessing
import threading
import time
import unittest
from unittest import mock

from review_bot.gitlab_webhook import ReviewManager

MR_FAIL = "https://gitlab.example.com/group/project/-/merge_requests/1"
MR_OK = "https://gitlab.example.com/group/project/-/merge_requests/2"


def _wait_for(predicate, timeout=5.0, interval=0.05):
    """Poll a predicate until it becomes true or the timeout expires.

    Args:
        predicate: Zero-argument callable evaluated repeatedly.
        timeout: Maximum number of seconds to keep polling.
        interval: Seconds to sleep between polls.

    Returns:
        True if the predicate returned True before the deadline, else False.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestWorkerResilience(unittest.TestCase):
    """The worker thread must survive failures while starting review processes."""

    def setUp(self):
        self.manager = ReviewManager(max_parallel=2)

    def tearDown(self):
        for p in list(self.manager.active.values()):
            if isinstance(p, multiprocessing.Process):
                p.terminate()
                p.join(timeout=2)
                if p.is_alive():
                    p.kill()
        self.manager.active.clear()

    def test_worker_survives_process_start_failure(self):
        failing = mock.MagicMock()
        failing.is_alive.return_value = True
        failing.start.side_effect = OSError("Resource temporarily unavailable")

        ok_proc = mock.MagicMock()
        ok_proc.is_alive.return_value = True

        procs = iter([failing, ok_proc])

        with mock.patch.object(
            multiprocessing, "Process", side_effect=lambda *a, **k: next(procs)
        ):
            with self.assertLogs("review_bot.gitlab_webhook", level="ERROR") as logs:
                self.manager.submit(MR_FAIL)
                self.assertTrue(
                    _wait_for(lambda: failing.start.called),
                    "worker never attempted to start the failing review",
                )
                self.assertTrue(
                    _wait_for(
                        lambda: any(
                            "Failed to start review" in rec for rec in logs.output
                        )
                    ),
                    "worker did not log the process-start failure",
                )

            self.assertNotIn(MR_FAIL, self.manager.active)
            self.assertEqual(self.manager.queue.count(MR_FAIL), 0)

            self.manager.submit(MR_OK)
            self.assertTrue(
                _wait_for(lambda: self.manager.active.get(MR_OK) is ok_proc),
                "worker thread died: second MR never became active",
            )

        self.assertTrue(self.manager.worker_thread.is_alive())
        self.assertNotIn(MR_FAIL, self.manager.active)


class TestSubmitRace(unittest.TestCase):
    """submit() must never leave a started review process untracked in active."""

    MR = "https://gitlab.example.com/group/project/-/merge_requests/1"

    def setUp(self):
        self.manager = ReviewManager(max_parallel=2)
        self.started: list[mock.MagicMock] = []
        self.killed: list[mock.MagicMock] = []
        self.kill_started = threading.Event()
        self.release_kill = threading.Event()
        self.first_kill = True

    def tearDown(self):
        self.release_kill.set()
        self.manager.active.clear()

    def _new_proc(self) -> mock.MagicMock:
        proc = mock.MagicMock()
        proc.is_alive.return_value = True
        self.started.append(proc)
        return proc

    def _fake_kill(self, proc: mock.MagicMock) -> None:
        if self.first_kill:
            self.first_kill = False
            self.kill_started.set()
            self.assertTrue(self.release_kill.wait(timeout=5))
        self.killed.append(proc)

    def test_submit_during_kill_window_leaves_no_orphan(self):
        with mock.patch.object(
            multiprocessing, "Process", side_effect=lambda *a, **k: self._new_proc()
        ):
            with mock.patch.object(
                self.manager, "_kill_process", side_effect=self._fake_kill
            ):
                self.manager.submit(self.MR)
                self.assertTrue(
                    _wait_for(
                        lambda: self.started
                        and self.manager.active.get(self.MR) is self.started[0]
                    ),
                    "first review never became active",
                )

                killer = threading.Thread(target=self.manager.submit, args=(self.MR,))
                killer.start()
                self.assertTrue(
                    self.kill_started.wait(timeout=5), "submit never entered the kill"
                )

                # Second event lands while the first submit blocks in the kill.
                self.manager.submit(self.MR)
                _wait_for(lambda: len(self.started) >= 2)

                self.release_kill.set()
                killer.join(timeout=10)

        self.assertTrue(_wait_for(lambda: not self.manager.queue), "queue never drained")
        time.sleep(0.5)  # grace period for any late (old-code) process start

        survivors = [p for p in self.started if p not in self.killed]
        self.assertEqual(
            len(survivors),
            1,
            f"expected exactly one un-killed process: "
            f"started={len(self.started)}, killed={len(self.killed)}",
        )
        self.assertIs(self.manager.active.get(self.MR), survivors[0])


if __name__ == "__main__":
    unittest.main()
