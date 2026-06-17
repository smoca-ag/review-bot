import logging
import os
import shutil
import sys
import tempfile
import unittest

from review_bot.backend.container_manager import ContainerManager

logger = logging.getLogger("container_security_test")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))


def _podman_available() -> bool:
    return shutil.which("podman") is not None


@unittest.skipUnless(_podman_available(), "podman not available")
class TestContainerSecurity(unittest.TestCase):
    container_mgr: ContainerManager
    tmpdir: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        with open(os.path.join(cls.tmpdir.name, ".gitkeep"), "w") as f:
            f.write("")

        cls.container_mgr = ContainerManager(logger)
        cls.container_mgr.setup(cls.tmpdir.name)

    @classmethod
    def tearDownClass(cls):
        cls.container_mgr.cleanup()
        if hasattr(cls, "tmpdir"):
            cls.tmpdir.cleanup()

    def _exec(self, command: str, timeout: int = 120) -> str:
        try:
            return self.container_mgr.execute_command(command, timeout=timeout)
        except Exception:
            return ""

    def test_01_no_new_privileges(self):
        out = self._exec("grep NoNewPrivs /proc/1/status || true")
        self.assertIn("NoNewPrivs:\t1", out)

    def test_02_capability_mask(self):
        out = self._exec("grep CapEff /proc/1/status || true")
        self.assertIn("CapEff:", out)
        cap_hex = out.strip().split("\t")[-1]
        cap_int = int(cap_hex, 16)

        dangerous = {12, 16, 17, 19, 21, 23, 34}
        for cap_bit in dangerous:
            self.assertFalse(
                cap_int & (1 << cap_bit),
                f"Dangerous capability bit {cap_bit} is set in CapEff={cap_hex}",
            )

    def test_03_apt_get_install_works(self):
        self._exec("apt-get update -qq", timeout=120)
        out = self._exec("apt-get install -y -qq hello", timeout=120)
        self.assertNotIn("E:", out)
        verify = self._exec("which hello || true")
        self.assertIn("hello", verify)

    def test_04_nginx_install_and_run(self):
        self._exec("apt-get update -qq && apt-get install -y -qq nginx", timeout=180)
        out = self._exec(
            "systemctl start nginx 2>&1 && systemctl is-active nginx || true"
        )
        self.assertIn("active", out)

        status = self._exec(
            "curl -s -o /dev/null -w '%{http_code}' http://localhost || true"
        )
        self.assertIn("200", status)

        self._exec("systemctl stop nginx 2>&1 || true")

    def test_05_postgres_install_and_run(self):
        self._exec(
            "apt-get update -qq && apt-get install -y -qq postgresql", timeout=180
        )
        out = self._exec(
            "systemctl start postgresql 2>&1 && systemctl is-active postgresql || true"
        )
        self.assertIn("active", out)

        self._exec("systemctl stop postgresql 2>&1 || true")

    def test_06_ping_works(self):
        apt_out = self._exec(
            "apt-get install -y -qq iputils-ping 2>&1 || true", timeout=120
        )
        self.assertNotIn("E:", apt_out)
        ping_out = self._exec("ping -c 1 -W 2 127.0.0.1 2>&1 || true")
        self.assertNotIn("Operation not permitted", ping_out)
        self.assertIn("1 packets transmitted, 1 received", ping_out)


if __name__ == "__main__":
    unittest.main()