import sys
from bs4 import BeautifulSoup
import os
from enum import Enum

from dotenv import load_dotenv
import argparse
import logging

from review_bot.git import Git
from review_bot.gitlab import Gitlab
from review_bot.diff import process_diff, paths_from_diff
from review_bot.review_bot import review

class BackendType(Enum):
    GITLAB = "gitlab"
    GIT = "git"
def backend_factory(backend):
    if backend == BackendType.GIT.value:
        return Git
    else:
        return Gitlab

def log_format_issue(issue):
    return f"{issue['severity']}:{issue['category']}:{issue['summary']} {issue['suggestion']} {issue['rationale']}"


def main():
    # Set up command line argument parser
    load_dotenv()

    parser = argparse.ArgumentParser(description='AI Code Review for GitLab Merge Requests')
    parser.add_argument('spec', type=str, help='Full Merge Request url or a argument for git diff')
    parser.add_argument('--post', action='store_true', help='Post the review directly to the merge request')
    parser.add_argument('--backend', type=str,choices=[backend.value for backend in BackendType], help='which backend to use, default to gitlab')

    args = parser.parse_args()


    # Get configuration from environment variables

    spec = args.spec
    review(spec, args.backend, args.post)

if __name__ == '__main__':
    sys.exit(main())
