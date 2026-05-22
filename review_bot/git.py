import subprocess


class Git:
    def __init__(self, logger, url):
        self.url = url

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

    def list_files(self, path="."):
        import subprocess

        try:
            output = subprocess.check_output(["ls", "-la", path], text=True)
            return output
        except subprocess.CalledProcessError as e:
            return f"Error listing files: {e}"

    def scan_code(self, pattern, path="."):
        import subprocess

        try:
            output = subprocess.check_output(
                ["git", "grep", "-n", pattern, path], text=True
            )
            return output
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return "No matches found."
            return f"Error scanning code: {e}"
