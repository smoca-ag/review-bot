import os
import subprocess

from opentelemetry import trace

from review_bot.backend.base_backend import BaseBackend

tracer = trace.get_tracer(__name__)


class Git(BaseBackend):
    def __init__(self, logger, url):
        super().__init__()
        self.url = url
        self.logger = logger
        self.repo_dir = os.path.abspath(".")

    def load(self):
        pass

    def diff(self):
        [code, diff] = subprocess.getstatusoutput(f"git diff  {self.url}")
        if code != 0:
            raise Exception(diff)
        return diff

    def title(self):
        return ""

    def description(self):
        return ""

    def post_line_review(self, issue, new_path, new_position):
        pass
