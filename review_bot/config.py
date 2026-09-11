import logging
import os

from dotenv import load_dotenv

from review_bot.infra.telemetry import setup_telemetry

SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".kts", ".scala", ".sh",
})

INDEX_EXTENSIONS: frozenset[str] = SOURCE_EXTENSIONS | frozenset({
    ".yaml", ".yml", ".toml", ".json", ".md",
})

EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", "node_modules", "venv", "env",
    ".venv", "dist", "build", ".gradle", ".idea", ".swiftpm",
    "Pods", "vendor",
})

EXCLUDE_DOT_DIRS: bool = True

AGENT_REQUEST_LIMIT: int = int(os.getenv("AGENT_REQUEST_LIMIT", "200"))


def _get_model() -> str:
    model_name = os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL") or os.getenv(
        "OPENAI_MODEL", "qwen3-coder:30b"
    )
    if os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL"):
        return f"anthropic:{model_name}"
    return f"openai:{model_name}"


def ensure_setup(logger: logging.Logger | None = None) -> None:
    """Load environment and initialise telemetry.

    Args:
        logger: Logger forwarded to telemetry setup for tool-call logging.
    """
    load_dotenv()
    setup_telemetry(logger)


def resolve_model() -> str:
    return _get_model()
