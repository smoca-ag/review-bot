"""Ask the local LLM to generate a JSON tool definition from a natural-language description.

Usage:
    python scripts/ask_tool_description.py "tool that lets an agent read a file from the repo"
    python scripts/ask_tool_description.py -- - <<'EOF'
    a utility to search code for regex patterns and return matching lines
    EOF

Requires .env with OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY (or ANTHROPIC_*).
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from openai import DefaultHttpxClient, OpenAI

SYSTEM_PROMPT = (
    "You are a tool schema generator. Output only valid JSON, no markdown. "
    "The JSON must have keys: name, description, parameters. "
    "parameters must be a JSON Schema object with type, properties, and required."
)


def _build_client() -> OpenAI:
    load_dotenv()
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    api_key = os.getenv("OPENAI_API_KEY", "unused")
    http_client = DefaultHttpxClient(timeout=500.0)
    return OpenAI(base_url=base_url, api_key=api_key, http_client=http_client)


def _get_model() -> str:
    return os.getenv("OPENAI_MODEL", "qwen3-coder:30b")


def ask(description: str) -> str:
    client = _build_client()
    model = _get_model()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Write the complete JSON function/tool definition "
                    f"(name, description, parameters schema) for {description}."
                ),
            },
        ],
        temperature=0.7,
        stream=False,
        max_tokens=2048,
    )

    content = response.choices[0].message.content
    return content.strip() if content else ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ask the LLM to generate a tool definition from a description."
    )
    parser.add_argument(
        "description",
        nargs="+",
        help="Natural-language description of the tool",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact JSON (single line)",
    )
    args = parser.parse_args()

    description = " ".join(args.description)
    result = ask(description)

    if not result:
        print("Error: empty response from model", file=sys.stderr)
        sys.exit(1)

    if args.compact:
        print(result)
    else:
        try:
            parsed = json.loads(result)
            print(json.dumps(parsed, indent=2))
        except json.JSONDecodeError:
            print(result)


if __name__ == "__main__":
    main()
