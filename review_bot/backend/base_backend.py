import asyncio
import logging
import os
import subprocess
import uuid
from typing import Optional


class Shell:
    """Persistent interactive shell inside a Podman container.

    Each instance owns a single ``podman exec -i /bin/sh`` process.
    Commands are sent to the shared shell so that stateful operations
    (``cd``, ``export``, etc.) persist across calls.
    """

    def __init__(
        self, container_name: str, logger: Optional[logging.Logger] = None
    ) -> None:
        self.container_name = container_name
        self.logger = logger
        self._marker: str = f"\x01{uuid.uuid4().hex}\x01"
        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        """Start (or restart) the shell process if needed."""
        if self._process is not None and self._process.returncode is None:
            return self._process

        self._process = await asyncio.create_subprocess_exec(
            "podman",
            "exec",
            "-i",
            "-e",
            f"PS1={self._marker}",
            self.container_name,
            "/bin/sh",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        proc = self._process

        # Merge stderr → stdout inside the shell so command errors appear
        # in the captured output.
        if proc.stdin is None:
            raise RuntimeError("Shell stdin unavailable.")
        proc.stdin.write(b"exec 2>&1\n")
        try:
            await asyncio.wait_for(proc.stdin.drain(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError("Shell init drain timed out.")

        # Consume the initial prompt (PS1 is printed right after shell starts).
        if proc.stdout is None:
            proc.kill()
            await proc.wait()
            raise RuntimeError("Shell stdout unavailable.")
        try:
            await asyncio.wait_for(
                proc.stdout.readuntil(self._marker.encode()),
                timeout=10,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError("Shell did not respond.")
        except Exception:
            # Covers LimitError (buffer overflow) and any other read failure.
            proc.kill()
            await proc.wait()
            raise RuntimeError("Shell init read failed.")

        if self.logger:
            self.logger.info(
                "Created persistent shell in container %s", self.container_name
            )

        return proc

    @staticmethod
    async def _read_until(
        stream: asyncio.StreamReader, marker: bytes, timeout: int
    ) -> bytes:
        """Read from *stream* until *marker* appears, handling large outputs."""
        buffer = b""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            data = await asyncio.wait_for(
                stream.read(8192), timeout=max(remaining, 0.1)
            )
            if not data:
                break  # EOF
            buffer += data
            if marker in buffer:
                idx = buffer.index(marker)
                return buffer[:idx]
        raise asyncio.TimeoutError()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, command: str, timeout: int = 60) -> str:
        """Run *command* in the persistent shell and return its output."""
        async with self._lock:
            proc = await self._ensure_process()
            marker = self._marker.encode()

            if proc.stdin is None or proc.stdout is None:
                proc.kill()
                await proc.wait()
                self._process = None
                return "Error: Shell I/O unavailable."

            try:
                proc.stdin.write(f"{command}\n".encode())
                await asyncio.wait_for(proc.stdin.drain(), timeout=timeout)
                output = await self._read_until(proc.stdout, marker, timeout)
                return output.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self._process = None
                return f"Error: Command timed out after {timeout} seconds."
            except Exception as exc:
                proc.kill()
                await proc.wait()
                self._process = None
                return f"Error executing command: {exc}"

    async def close(self) -> None:
        """Gracefully shut down the shell process."""
        if self._process is not None and self._process.returncode is None:
            if self._process.stdin is not None:
                self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            if self.logger:
                self.logger.info("Closed persistent shell")


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

    def create_shell(self) -> Shell:
        """Return a new :class:`Shell` tied to the current container.

        Raises ``RuntimeError`` if no container is active.
        """
        if not self.container_name:
            raise RuntimeError("No active container found.")
        return Shell(self.container_name, self.logger)

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
