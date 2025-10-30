import sys
from bs4 import BeautifulSoup
import os
from enum import Enum

from dotenv import load_dotenv
import argparse
import logging

from review_bot.ai import AI
from review_bot.git import Git
from review_bot.gitlab import Gitlab
from review_bot.prompts import Prompts
from review_bot.diff import process_diff, paths_from_diff

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


def review(spec, backend, post=False):
    # setup logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    openai_model = os.getenv('OPENAI_MODEL', 'qwen3-coder:30b')
    openai_url = os.getenv('OPENAI_URL', 'http://localhost:11434/v1')
    openai_api_key = os.getenv('OPENAI_API_KEY', '')


    prompts = Prompts(logger)
    ai_model = AI(logger, openai_url, openai_api_key, openai_model)
    mr_request = backend_factory(backend)(logger, spec)
    logger.info(f"Load the Merge Request {spec}")

    mr_request.load()

    diff_content = mr_request.diff()
    paths = paths_from_diff(diff_content)
    logger.info(f"Load the files {paths}")

    files = mr_request.get_files(paths)

    logger.info(f"Send the main prompt")
    context_prompt = prompts.main_prompt(mr_request.title(), diff_content, files)
    response = ai_model.question_persistent(context_prompt)
    logger.info(f"Full review response {response}")

    logger.info(f"Format the output")
    output_prompt = prompts.output_prompt()
    response = ai_model.question_persistent(output_prompt)
    soup = BeautifulSoup(response, 'html.parser')
    summary = soup.find('summary').text.strip()
    conclusion = soup.find('conclusion').text.strip()
    logger.info(f"summary: {summary}")
    for finding in soup.find_all('finding'):
        severity = finding.find('severity').text.strip()
        category = finding.find('category').text.strip()
        comment = finding.find('comment').text.strip()
        line = finding.find('line').text.strip()
        file = finding.find('file').text.strip()
        text = f"**{severity}/{category}**: {comment}"
        logger.info(f"{file}:{line}: {text}")
        if post:
            mr_request.post_line_review(text, None, file, None, line)


    logger.info(f"conclusion: {conclusion}")
    mr_request.post_review(conclusion)

if __name__ == '__main__':
    sys.exit(main())