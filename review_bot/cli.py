import argparse
import sys

from dotenv import load_dotenv

from review_bot import BackendType, backend_factory, review


def main():
    """CLI entry point for the review-bot command."""
    load_dotenv()

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

    review(spec=args.spec, backend=args.backend, post=args.post)


if __name__ == "__main__":
    sys.exit(main())
