import os
import subprocess
import uuid


class BaseBackend:
    def __init__(self):
        self.repo_dir = None
        self.container_name = None

    def list_files(self, path="."):
        if not self.repo_dir:
            return "Repository not fetched locally."
        try:
            output = subprocess.check_output(
                ["ls", "-la", path], cwd=self.repo_dir, text=True
            )
            return output
        except subprocess.CalledProcessError as e:
            return f"Error listing files: {e}"

    def scan_code(self, pattern, path="."):
        if not self.repo_dir:
            return "Repository not fetched locally."
        try:
            output = subprocess.check_output(
                ["git", "grep", "-n", pattern, path], cwd=self.repo_dir, text=True
            )
            return output
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return "No matches found."
            return f"Error scanning code: {e}"

    def get_file(self, file_path):
        """
        Fetches the content of a file from the locally cloned repository.
        """
        if not getattr(self, "repo_dir", None):
            return None

        full_path = os.path.join(self.repo_dir, file_path)
        try:
            with open(full_path, "r") as f:
                return f.read()
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.error(
                    f"Error reading file {file_path} from local repo: {e}"
                )
            return None

    def get_files(self, paths):
        paths_dict = {}
        for path in paths:
            paths_dict[path] = self.get_file(path)
        return paths_dict

    def setup_container(self, image="python:3.11-slim"):
        if not getattr(self, "repo_dir", None):
            if hasattr(self, "logger"):
                self.logger.error("No repository directory to mount.")
            return

        self.container_name = f"review-bot-{uuid.uuid4().hex[:8]}"
        abs_repo_dir = os.path.abspath(self.repo_dir)
        subprocess.check_call(
            [
                "podman",
                "run",
                "-d",
                "--rm",
                "--name",
                self.container_name,
                "-v",
                f"{abs_repo_dir}:/workspace",
                "-w",
                "/workspace",
                image,
                "sleep",
                "infinity",
            ]
        )
        if hasattr(self, "logger"):
            self.logger.info(f"Started Podman container: {self.container_name}")

    def execute_command(self, command: str, timeout: int = 60) -> str:
        if not getattr(self, "container_name", None):
            return "Error: No active container found."

        try:
            output = subprocess.check_output(
                ["podman", "exec", self.container_name, "sh", "-c", command],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
            return output
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds."
        except subprocess.CalledProcessError as e:
            return f"Command failed with exit code {e.returncode}:\n{e.output}"

    def cleanup(self):
        if getattr(self, "container_name", None):
            try:
                subprocess.check_call(
                    ["podman", "kill", self.container_name], stdout=subprocess.DEVNULL
                )
                if hasattr(self, "logger"):
                    self.logger.info(f"Cleaned up container: {self.container_name}")
            except subprocess.CalledProcessError as e:
                if hasattr(self, "logger"):
                    self.logger.error(
                        f"Failed to kill container {self.container_name}: {e}"
                    )
            finally:
                self.container_name = None
