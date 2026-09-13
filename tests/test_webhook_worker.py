"""Tests for ReviewManager worker resilience against process-start failures."""

import multiprocessing
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


if __name__ == "__main__":
    unittest.main()
