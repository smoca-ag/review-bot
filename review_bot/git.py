import os
import subprocess

from review_bot.base_backend import BaseBackend


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

    def get_file(self, path):
        with open(path, "r") as file:
            return file.read()

    def post_line_review(self, issue, old_path, new_path, old_position, new_position):
        pass
