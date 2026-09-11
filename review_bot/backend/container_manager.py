"""Manages a sandboxed Podman container for code review tool execution.

Independent of MR data, diff loading, and review posting. The container is
mounted as a plain bind mount so that anything agents install inside the
sandbox (node_modules, gems, ...) survives a transparent container restart.

Container names embed the creating process's PID (``review-bot-p<PID>-<hex>``)
so :func:`prune_stale_containers` can reclaim containers whose owner died
without running ``cleanup()`` (SIGKILL, OOM, crash, host quirk).
"""

import logging
import os
import re
import subprocess
import time
import uuid
from typing import Callable

SANDBOX_UNAVAILABLE_MESSAGE = (
    "Error: sandbox container unavailable and could not be restarted. "
    "Tool-based verification impossible — mark affected findings inconclusive "
    "and state that verification was not tool-based."
)

_OWNER_PID_RE = re.compile(r"^review-bot-p(\d+)-[0-9a-f]{8}$")
_OWNER_NAME_FILTER = "^review-bot-p"
_BRACE_GROUP_RE = re.compile(r"\{([^{}]*,[^{}]*)\}")
_MAX_EXPANDED_PATTERNS = 32
_MAX_EXPANSION_PASSES = 8


def expand_braces(pattern: str) -> list[str]:
    """Expand a glob pattern with brace alternation into plain patterns.

    Supports one or more ``{a,b}`` groups (including nested groups, expanded
    innermost first). Groups without a comma are left literal. Pathological
    patterns expanding beyond the cap are returned unchanged.

    Args:
        pattern: Glob pattern, possibly containing brace groups.

    Returns:
        List of expanded patterns; a single-element list with the original
        pattern when it contains no expandable braces or exceeds the cap.
    """
    patterns = [pattern]
    for _ in range(_MAX_EXPANSION_PASSES):
        expanded: list[str] = []
        changed = False
        for current in patterns:
            match = _BRACE_GROUP_RE.search(current)
            if not match:
                expanded.append(current)
                continue
            changed = True
            for alternative in match.group(1).split(","):
                expanded.append(
                    current[: match.start()] + alternative + current[match.end():]
                )
        if not changed:
            break
        if len(expanded) > _MAX_EXPANDED_PATTERNS:
            return [pattern]
        patterns = expanded
    return patterns


class ContainerManager:
    """Manages a sandboxed Podman container for code review tool execution.

    If the container dies mid-review (e.g. reclaimed by the host), the next
    tool call restarts it once from the same image and mount; writes made by
    earlier commands survive because ``/workspace`` is a plain bind mount.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.container_name: str | None = None
        self.repo_dir: str | None = None
        self.image: str | None = None

    def setup(self, repo_dir: str, image: str = "review-bot-env:latest") -> None:
        """Create a sandboxed Podman container with the repository mounted.

        Args:
            repo_dir: Host directory containing the repository checkout.
            image: Container image to run.

        Raises:
            RuntimeError: When the image build, container start, or startup
                health check fails.
        """
        if not repo_dir:
            if self.logger:
                self.logger.error("No repository directory to mount.")
            return

        self.repo_dir = repo_dir
        self.image = image

        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        build_dir = os.path.join(project_root, "review-container")
        build_result = subprocess.run(["podman", "build", "-t", image, build_dir])
        if build_result.returncode != 0:
            raise RuntimeError("Failed to build the review-container image.")

        self._start_container()
        self._wait_until_ready()

        if self.logger:
            self.logger.info(f"Started Podman container: {self.container_name}")

    def _start_container(self) -> None:
        """Start the sandbox container under a fresh name.

        Raises:
            RuntimeError: When podman fails to start the container or times out.
        """
        assert self.repo_dir is not None and self.image is not None

        self.container_name = f"review-bot-p{os.getpid()}-{uuid.uuid4().hex[:8]}"
        abs_repo_dir = os.path.abspath(self.repo_dir)
        try:
            result = subprocess.run(
                [
                    "podman",
                    "run",
                    "-d",
                    "-t",
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
                    "--memory=8g",
                    "--memory-swap=8g",
                    "--cpus=4",
                    "--pids-limit=8192",
                    "--name",
                    self.container_name,
                    "-v",
                    f"{abs_repo_dir}:/workspace",
                    "-w",
                    "/workspace",
                    self.image,
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

    def _wait_until_ready(self, timeout: float = 15.0) -> None:
        """Block until the container accepts exec sessions.

        Args:
            timeout: Maximum seconds to wait for the container to become ready.

        Raises:
            RuntimeError: When the container is not ready within the timeout.
        """
        assert self.container_name is not None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                probe = subprocess.run(
                    ["podman", "exec", self.container_name, "true"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if probe.returncode == 0:
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.5)

        raise RuntimeError(
            f"Sandbox container {self.container_name} did not become ready "
            f"within {timeout} seconds."
        )

    def _is_container_missing(self, output: str, returncode: int) -> bool:
        """Return True when a podman failure indicates the sandbox is gone."""
        return returncode == 125 or "no container with name or ID" in output

    def _ensure_available(self) -> bool:
        """Ensure a sandbox container is running, restarting it once if needed.

        Returns:
            True when a container is (again) available; False when no container
            is running and the restart attempt failed.
        """
        if not self.container_name or not self.repo_dir or not self.image:
            return False

        try:
            ps = subprocess.run(
                [
                    "podman",
                    "ps",
                    "--filter",
                    f"name=^{self.container_name}$",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if ps.returncode == 0 and self.container_name in ps.stdout.split():
                return True
        except subprocess.TimeoutExpired:
            pass

        old_name = self.container_name
        if self.logger:
            self.logger.warning(
                f"Sandbox container {old_name} is gone; attempting restart..."
            )
        try:
            self._start_container()
            self._wait_until_ready()
            if self.logger:
                self.logger.info(
                    f"Restarted sandbox container as {self.container_name} "
                    f"(was {old_name})."
                )
            return True
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            if self.logger:
                self.logger.error(f"Failed to restart sandbox container: {e}")
            return False

    def _run_with_restart(
        self, run: Callable[[], subprocess.CompletedProcess]
    ) -> subprocess.CompletedProcess | str:
        """Run a podman exec command, restarting the sandbox once if it died.

        Args:
            run: Zero-arg callable that builds and runs the podman command
                against the current ``self.container_name``; called again on
                retry so a restarted container's new name is picked up.

        Returns:
            The CompletedProcess of the (possibly retried) run, or
            ``SANDBOX_UNAVAILABLE_MESSAGE`` when the sandbox died and could
            not be restarted.

        Raises:
            subprocess.CalledProcessError: When the command itself fails.
            subprocess.TimeoutExpired: When the command times out.
        """
        try:
            output = run()
        except subprocess.CalledProcessError as e:
            if not self._is_container_missing(e.stdout or "", e.returncode):
                raise
            if not self._ensure_available():
                return SANDBOX_UNAVAILABLE_MESSAGE
            return run()

        if (
            output.returncode != 0
            and self._is_container_missing(output.stdout or "", output.returncode)
        ):
            if not self._ensure_available():
                return SANDBOX_UNAVAILABLE_MESSAGE
            return run()
        return output

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

        def _run() -> subprocess.CompletedProcess:
            assert self.container_name is not None
            cmd: list[str] = ["podman", "exec"]
            if working_directory:
                cmd.extend(["--workdir", working_directory])
            if environment:
                for key, value in environment.items():
                    cmd.extend(["--env", f"{key}={value}"])
            cmd.extend([self.container_name, "/bin/bash", "-c", command])
            return subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=True,
            )

        try:
            output = self._run_with_restart(_run)
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds."
        except subprocess.CalledProcessError as e:
            err_output: str = e.stdout if e.stdout else "(no output)"
            return f"Command failed with exit code {e.returncode}:\n{err_output}"
        if isinstance(output, str):
            return output
        return output.stdout

    def get_file_raw(self, file_path: str) -> str | None:
        """Return raw file content from the container without line-number formatting.

        Args:
            file_path: Path of the file inside the container.

        Returns:
            The file content, ``None`` when the file does not exist, or an
            error message string when the sandbox or read fails.
        """
        if not self.container_name:
            return "Error: No active container found."

        def _run() -> subprocess.CompletedProcess:
            assert self.container_name is not None
            return subprocess.run(
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

        try:
            output = self._run_with_restart(_run)
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        if isinstance(output, str):
            return output

        if output.returncode != 0:
            error_msg = output.stdout or ""
            if "No such file" in error_msg or "cannot access" in error_msg:
                return None
            return f"Error reading file {file_path}: {error_msg.strip()}"
        return output.stdout

    def list_files(self, path: str = ".", recursive: bool = False) -> str:
        """List files in the repository at the given path inside the container."""
        if not self.container_name:
            return "Error: No active container found."

        def _run() -> subprocess.CompletedProcess:
            assert self.container_name is not None
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
            return subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                check=True,
            )

        try:
            output = self._run_with_restart(_run)
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            err_output = e.stdout.strip() if e.stdout else "(no output)"
            return f"Error listing files: {err_output}"
        if isinstance(output, str):
            return output
        return output.stdout

    def glob_files(self, pattern: str) -> str:
        """Find files matching glob pattern(s) inside the container.

        Supports brace alternation such as ``**/*.{test,spec}.ts`` by expanding
        it into multiple patterns, then unioning the matches.

        Args:
            pattern: Glob pattern, possibly with brace groups.

        Returns:
            Newline-separated matching paths, ``No files matched.`` when empty,
            or an error message string.
        """
        if not self.container_name:
            return "Error: No active container found."

        patterns = expand_braces(pattern)

        def _run() -> subprocess.CompletedProcess:
            assert self.container_name is not None
            script = (
                "import glob, sys\n"
                "seen = set()\n"
                "for pat in sys.argv[1:]:\n"
                "    for f in sorted(glob.glob(pat, recursive=True)):\n"
                "        if f not in seen:\n"
                "            seen.add(f)\n"
                "            print(f)"
            )
            return subprocess.run(
                [
                    "podman",
                    "exec",
                    "-w",
                    "/workspace",
                    self.container_name,
                    "python3",
                    "-c",
                    script,
                    *patterns,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                check=True,
            )

        try:
            output = self._run_with_restart(_run)
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds."
        except subprocess.CalledProcessError as e:
            err_output = e.stdout.strip() if e.stdout else "(no output)"
            return f"Error globbing files: {err_output}"
        if isinstance(output, str):
            return output
        return output.stdout or "No files matched."


def _owner_pid(container_name: str) -> int | None:
    """Return the PID embedded in a container name, or None if unparseable."""
    match = _OWNER_PID_RE.match(container_name)
    return int(match.group(1)) if match else None


def _process_alive(pid: int) -> bool:
    """Return True when a process with the given PID currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def prune_stale_containers(
    logger: logging.Logger | None = None, timeout: int = 15
) -> int:
    """Remove sandbox containers whose owning review process is dead.

    Containers are named ``review-bot-p<PID>-<hex>``; a container is stale
    when no process with ``<PID>`` exists anymore. PID reuse can make a dead
    owner look alive, which only delays reclamation until that PID is free
    again — a live-PID container is never removed, so long-running reviews
    are always safe.

    Args:
        logger: Optional logger for removal and failure reporting.
        timeout: Per-podman-call timeout in seconds.

    Returns:
        The number of containers removed.
    """
    try:
        ps = subprocess.run(
            [
                "podman",
                "ps",
                "--all",
                "--filter",
                f"name={_OWNER_NAME_FILTER}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        if logger:
            logger.warning(f"Stale container sweep could not list containers: {e}")
        return 0

    if ps.returncode != 0:
        if logger:
            logger.warning(f"Stale container sweep failed to list containers: {ps.stderr}")
        return 0

    removed = 0
    for name in ps.stdout.split():
        pid = _owner_pid(name)
        if pid is None or _process_alive(pid):
            continue
        try:
            rm = subprocess.run(
                ["podman", "rm", "-f", name],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            if logger:
                logger.warning(f"Failed to remove stale container {name}: {e}")
            continue
        if rm.returncode != 0:
            if logger:
                logger.warning(f"Failed to remove stale container {name}: {rm.stderr}")
            continue
        removed += 1
        if logger:
            logger.info(f"Removed stale sandbox container: {name}")
    return removed
