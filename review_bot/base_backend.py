import os
import subprocess
import uuid


class BaseBackend:
    def __init__(self):
        self.repo_dir = None
        self.container_name = None

    def load(self):
        pass

    def is_open(self) -> bool:
        """
        Returns True if the merge request is open and eligible for review.
        """
        return True

    def is_draft(self) -> bool:
        """
        Returns True if the merge request is a draft/WIP.
        """
        return False

    def list_files(self, path="."):
        if not getattr(self, "container_name", None):
            return "Error: No active container found."

        try:
            output = subprocess.check_output(
                ["podman", "exec", self.container_name, "sh", "-c", f"ls -la '{path}'"],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            return f"Error listing files: {e.output.strip()}"

    def scan_code(self, pattern, path="."):
        if not getattr(self, "container_name", None):
            return "Error: No active container found."

        try:
            output = subprocess.check_output(
                [
                    "podman",
                    "exec",
                    self.container_name,
                    "sh",
                    "-c",
                    f"git grep -n '{pattern}' '{path}'",
                ],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return "No matches found."
            return f"Error scanning code: {e.output.strip()}"

    def get_file_raw(self, file_path: str):
        """Return raw file content (str or bytes) from the container without line-number formatting.

        Used by the fetch_file_content tool for pagination and binary detection.
        """
        if not getattr(self, "container_name", None):
            return "Error: No active container found."

        try:
            # Read file as bytes directly
            output = subprocess.check_output(
                [
                    "podman",
                    "exec",
                    self.container_name,
                    "cat",
                    file_path,
                ],
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            error_msg = e.output.decode("utf-8", errors="replace")
            if "No such file" in error_msg or "cannot access" in error_msg:
                return None
            return f"Error reading file {file_path}: {error_msg.strip()}"

    def setup_container(self, image="python:3.11"):
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
                "--cap-drop=ALL",
                "--name",
                self.container_name,
                "-v",
                f"{abs_repo_dir}:/workspace:O",
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

    def publish_reviews(self):
        pass

    def post_line_review(self, text, old_path, new_path, old_position, new_position):
        pass

    def post_review(self, text):
        pass

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
