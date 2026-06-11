import logging
import os
import subprocess

from opentelemetry import trace

from review_bot.backend.base_backend import BaseBackend

tracer = trace.get_tracer(__name__)


class Git(BaseBackend):
    def __init__(self, logger: logging.Logger, url: str):
        super().__init__(logger, url)
        self.repo_dir = os.path.abspath(".")

    def load(self) -> None:
        pass

    def diff(self) -> str:
        """Get the git diff for the specified ref."""
        result = subprocess.run(
            ["git", "diff", self.url],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff failed: {result.stderr}")
        return result.stdout

    def title(self) -> str:
        return ""

    def description(self) -> str:
        return ""
