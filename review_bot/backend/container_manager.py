import logging
import os
import subprocess
import uuid
from typing import Optional


class ContainerManager:
    """Manages a sandboxed Podman container for code review tool execution.

    Independent of MR data, diff loading, and review posting.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.container_name: Optional[str] = None

    def setup(self, repo_dir: str, image: str = "review-bot-env:latest") -> None:
        """Create a sandboxed Podman container with the repository mounted."""
        if not repo_dir:
            if self.logger:
                self.logger.error("No repository directory to mount.")
            return

        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        build_dir = os.path.join(project_root, "review-container")
        build_result = subprocess.run(["podman", "build", "-t", image, build_dir])
        if build_result.returncode != 0:
            raise RuntimeError("Failed to build the review-container image.")

        self.container_name = f"review-bot-{uuid.uuid4().hex[:8]}"
        abs_repo_dir = os.path.abspath(repo_dir)
        try:
            result = subprocess.run(
                [
                    "podman",
                    "run",
                    "-d",
                    "--rm",
                    "--systemd=always",
                    "--security-opt=no-new-privileges:true",
                    "--cap-drop=ALL",
                    "--cap-add=CAP_NET_BIND_SERVICE",
                    "--cap-add=CAP_NET_RAW",
                    "--cap-add=CAP_CHOWN",
                    "--cap-add=CAP_DAC_OVERRIDE",
                    "--cap-add=CAP_FOWNER",
                    "--cap-add=CAP_SETUID",
                    "--cap-add=CAP_SETGID",
                    "--cap-add=CAP_KILL",
                    "--cap-add=CAP_SYS_CHROOT",
                    "--memory=4g",
                    "--memory-swap=4g",
                    "--cpus=2",
                    "--name",
                    self.container_name,
                    "-v",
                    f"{abs_repo_dir}:/workspace:O",
                    "-w",
                    "/workspace",
                    image,
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

    def cleanup(self) -> None:
        """Kill and clean up the Podman container."""
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

    def execute_command(
        self,
        command: str,
        timeout: int = 60,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        """Execute a shell command inside the container."""
        if not self.container_name:
            return "Error: No active container found."

        try:
            cmd: list[str] = ["podman", "exec"]
            if working_directory:
                cmd.extend(["--workdir", working_directory])
            if environment:
                for key, value in environment.items():
                    cmd.extend(["--env", f"{key}={value}"])
            cmd.extend([self.container_name, "/bin/bash", "-c", command])
            output = subprocess.run(
                cmd,
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
            err_output: str = e.stdout if e.stdout else "(no output)"
            return f"Command failed with exit code {e.returncode}:\n{err_output}"
        except ValueError:
            return "Error: Failed to parse command."

    def get_file_raw(self, file_path: str) -> Optional[str]:
        """Return raw file content from the container without line-number formatting.

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
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            error_msg = e.stdout or ""
            if "No such file" in error_msg or "cannot access" in error_msg:
                return None
            return f"Error reading file {file_path}: {error_msg.strip()}"

    def list_files(self, path: str = ".", recursive: bool = False) -> str:
        """List files in the repository at the given path inside the container."""
        if not self.container_name:
            return "Error: No active container found."

        try:
            cmd = (
                [
                    "podman",
                    "exec",
                    self.container_name,
                    "find",
                    path,
                    "-type",
                    "f",
                    "-o",
                    "-type",
                    "d",
                ]
                if recursive
                else ["podman", "exec", self.container_name, "ls", "-1a", path]
            )
            output = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                check=True,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            err_output = e.stdout.strip() if e.stdout else "(no output)"
            return f"Error listing files: {err_output}"

    def scan_code(self, pattern: str, path: str = ".") -> str:
        """Scan the repository for a pattern using grep inside the container."""
        if not self.container_name:
            return "Error: No active container found."

        try:
            output = subprocess.run(
                [
                    "podman",
                    "exec",
                    "-w",
                    "/workspace",
                    self.container_name,
                    "grep",
                    "-rn",
                    pattern,
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            return output.stdout
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return "No matches found."
            err_output = e.stdout.strip() if e.stdout else "(no output)"
            return f"Error scanning code: {err_output}"
