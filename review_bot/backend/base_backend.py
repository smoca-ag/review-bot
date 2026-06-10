import asyncio
import logging
import os
import subprocess
import uuid
from typing import Optional

class BaseBackend:
    def __init__(self, logger: logging.Logger, url: str) -> None:
        self.url = url
        self.repo_dir: Optional[str] = None
        self.container_name: Optional[str] = None
        self.logger: logging.Logger = logger

    def load(self) -> None:
        pass

    def is_open(self) -> bool:
        """Returns True if the merge request is open and eligible for review."""
        return True

    def is_draft(self) -> bool:
        """Returns True if the merge request is a draft/WIP."""
        return False


    def list_files(self, path: str = ".") -> str:
        """List files in the repository at the given path inside the container."""
        if not self.container_name:
            return "Error: No active container found."

        try:
            output = subprocess.run(
                ["podman", "exec", self.container_name, "ls", "-la", path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            return f"Error listing files: {e.stdout.strip()}"

    def scan_code(self, pattern: str, path: str = ".") -> str:
        """Scan the repository for a pattern using git grep inside the container."""
        if not self.container_name:
            return "Error: No active container found."

        try:
            output = subprocess.run(
                [
                    "podman",
                    "exec",
                    self.container_name,
                    "git",
                    "grep",
                    "-n",
                    pattern,
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return "No matches found."
            return f"Error scanning code: {e.stdout.strip()}"

    def execute_command(self, command: str, timeout: int = 60) -> str:
        """Execute a shell command inside the container"""
        if not self.container_name:
            return "Error: No active container found."

        try:
            output = subprocess.run(
                ["podman", "exec", "/bin/sh", "-c", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=True,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds."
        except subprocess.CalledProcessError as e:
            return f"Command failed with exit code {e.returncode}:\n{e.stdout}\n{e.stderr}"
        except ValueError:
            return "Error: Failed to parse command."

    def get_file_raw(self, file_path: str) -> Optional[str]:
        """Return raw file content from the container without line-number formatting.

        Used by the fetch_file_content tool for pagination and binary detection.
        Returns ``None`` when the file does not exist.
        """
        if not self.container_name:
            return "Error: No active container found."

        try:
            output = subprocess.run(
                [
                    "podman",
                    "exec",
                    self.container_name,
                    "cat",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr
            if "No such file" in error_msg or "cannot access" in error_msg:
                return None
            return f"Error reading file {file_path}: {error_msg.strip()}"

    def setup_container(self, image: str = "python:3.11") -> None:
        """Create a sandboxed Podman container with the repository mounted."""
        if not self.repo_dir:
            if self.logger:
                self.logger.error("No repository directory to mount.")
            return

        self.container_name = f"review-bot-{uuid.uuid4().hex[:8]}"
        abs_repo_dir = os.path.abspath(self.repo_dir)
        try:
            result = subprocess.run(
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
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to start Podman container: {result.stderr}")
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"Failed to start Podman container (timeout): {e}"
            ) from e

        if self.logger:
            self.logger.info(f"Started Podman container: {self.container_name}")

    def publish_reviews(self) -> None:
        pass

    def diff(self) -> str:
        return ""

    def description(self) -> Optional[str]:
        return None

    def title(self) -> Optional[str]:
        return None

    def post_line_review(self, text: str, new_path: str, new_position: int) -> None:
        pass

    def post_review(self, text: str) -> None:
        pass

    def cleanup(self) -> None:
        """Clean up the Podman container."""
        if self.container_name:
            try:
                subprocess.run(
                    ["podman", "kill", self.container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                if self.logger:
                    self.logger.info(f"Cleaned up container: {self.container_name}")
            except subprocess.CalledProcessError as e:
                if self.logger:
                    self.logger.error(
                        f"Failed to kill container {self.container_name}: {e}"
                    )
            except subprocess.TimeoutExpired:
                if self.logger:
                    self.logger.warning(
                        f"Timeout killing container {self.container_name}, attempting remove"
                    )
                    try:
                        subprocess.run(
                            ["podman", "rm", "-f", self.container_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                        )
                    except Exception:
                        pass
            finally:
                self.container_name = None
