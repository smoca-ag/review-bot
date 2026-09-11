"""Tests for signal handling in spawned review processes."""

import os
import signal
import unittest

from review_bot.gitlab_webhook import _raise_on_sigterm


class TestSigtermHandler(unittest.TestCase):
    def tearDown(self):
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def test_sigterm_raises_systemexit_and_ignores_followups(self):
        signal.signal(signal.SIGTERM, _raise_on_sigterm)

        with self.assertRaises(SystemExit) as ctx:
            os.kill(os.getpid(), signal.SIGTERM)

        self.assertEqual(ctx.exception.code, 143)
        self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_IGN)


if __name__ == "__main__":
    unittest.main()
