from review_bot.models import ReviewDeps
from review_bot.utils.text import paginate_text
from pydantic_ai import RunContext


async def execute_command(
    ctx: RunContext[ReviewDeps],
    command: str,
    timeout_seconds: int = 60,
    working_directory: str | None = None,
    environment: dict[str, str] | None = None,
    start_line: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    Execute a shell command in the repository context.

    Use this tool inside a container to run tests,
    linters, or other build scripts to verify code correctness.
    The source code is checked out to /workspace.

    You are strongly encouraged to use this tool to verify your findings.
    For example: `pytest tests/`, `mypy src/`, `npm run test`, `node -e "..."`, `python -c "..."`.
    Use `rg <pattern> [path]` (ripgrep) for fast regex code searches, e.g.
    `rg 'foo|bar' src/` — full regex including alternation is supported.

    Long builds or test suites: start them in the background writing to a log
    file (e.g. `nohup make build > /tmp/build.log 2>&1 &`) and then poll the
    log with short commands like `tail -50 /tmp/build.log` instead of sleeping
    or blocking for the whole duration.

    Args:
        command: The shell command to execute.
        timeout_seconds: Maximum allowed execution time in seconds (default 60).
        working_directory: The directory to set as the current working directory for command execution.
        environment: Environment variables to set for the command, as key-value pairs.
        start_line: The line number to start reading output from for pagination.
        max_lines: The maximum number of lines of output to return.
    """
    try:
        raw = ctx.deps.container_manager.execute_command(
            command,
            timeout=timeout_seconds,
            working_directory=working_directory,
            environment=environment,
        )
        return paginate_text(raw, start_line, max_lines)
    except Exception as e:
        return f"Error executing command: {str(e)}"