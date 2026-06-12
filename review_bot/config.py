import os

from dotenv import load_dotenv

from review_bot.telemetry import setup_telemetry


def _get_model() -> str:
    model_name = os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL") or os.getenv(
        "OPENAI_MODEL", "qwen3-coder:30b"
    )
    if os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL"):
        return f"anthropic:{model_name}"
    return f"openai:{model_name}"


def ensure_setup() -> None:
    load_dotenv()
    setup_telemetry()


def resolve_model() -> str:
    return _get_model()
