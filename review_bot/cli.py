import argparse
import asyncio
import sys

from dotenv import load_dotenv

# Load .env before importing review_bot: config constants
# (AGENT_REQUEST_LIMIT, CONFIDENCE_THRESHOLD, MAX_LINES, ...) are captured
# at import time and would otherwise miss .env values.
load_dotenv()

from review_bot import BackendType, review  # noqa: E402


async def async_main():
    """Async entry point for the review-bot command."""
    parser = argparse.ArgumentParser(
        description="AI Code Review for GitLab Merge Requests"
    )
    parser.add_argument(
        "spec", type=str, help="Full Merge Request url or an argument for git diff"
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post the review directly to the merge request",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=[b.value for b in BackendType],
        default=BackendType.GITLAB.value,
        help="Which backend to use (default: gitlab)",
    )

    args = parser.parse_args()

    await review(spec=args.spec, backend=args.backend, post=args.post)


def main():
    """CLI entry point for the review-bot command."""
    asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
