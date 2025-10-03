import sys
import json
import os
from enum import Enum

from dotenv import load_dotenv
import argparse
import logging

from lib.ai import AI
from lib.git import Git
from lib.gitlab import Gitlab
from lib.prompts import Prompts
from lib.diff import process_diff, paths_from_diff

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
    # setup logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # Get configuration from environment variables
    openai_model = os.getenv('OPENAI_MODEL', 'qwen3-coder:30b')
    openai_url = os.getenv('OPENAI_URL', 'http://localhost:11434/v1')
    openai_api_key = os.getenv('OPENAI_API_KEY', 'ollama')

    spec = args.spec


    prompts = Prompts(logger)
    ai_model = AI(logger, openai_url, openai_api_key, openai_model)
    mr_request = backend_factory(args.backend)(logger, spec)
    logger.info(f"Load the Merge Request {spec}")

    mr_request.load()

    diff_content = mr_request.diff()
    paths = paths_from_diff(diff_content)
    logger.info(f"Load the files {paths}")

    files = mr_request.get_files(paths)



    logger.info(f"Send the context prompt")
    context_prompt = prompts.context_prompt(mr_request.title(), diff_content, files)
    ai_model.question_persistent(context_prompt)

    logger.info(f"iterate over changes")
    collected_reviews = []
    last_removed_line = ""

    for change_type, old_pos, new_pos, content, old_path, new_path in process_diff(diff_content):
        logger.info(f"{content}")
        if change_type == "deleted":
            last_removed_line = content
            continue
        if change_type != "added":
            continue
        if content.strip() == "":
            continue
        # remove whitespace only changes
        if last_removed_line.strip() == content[1:].strip():
            last_removed_line = ""
            continue
        last_removed_line = ""

        code_around = "\n".join(files[new_path].split("\n")[new_pos - 6 : new_pos + 4])
        question = prompts.line_prompt(new_path, new_pos, content[1:], code_around)
        response = ai_model.question_json(question)
        review = response.get('review', {})
        severity = review.get('severity', '')
        suggestion = review.get('suggestion', '')
        if severity == "pass" or len(suggestion) == 0:
            continue
        logger.warning(f"{suggestion}")
        collected_reviews.append({"new_path": new_path, "new_pos": new_pos, "review": review})

    logger.info(f"collected issues {collected_reviews}")
    question = prompts.consolidatePrompt(collected_reviews)
    response = ai_model.question_json(question)
    for review in response:
        try:
            new_path = review['new_path']
            new_pos = review['new_pos']
            review = review['review']
            suggestion = review.get('suggestion', '')
            logger.info(f"{new_path} {new_pos} {suggestion}")
        except KeyError as e:
            logger.error(f"Error parsing response json from LLM: {e} {review}")

    # Post inline comments to GitLab
    if not args.post:
        logger.info("Review generated but not posted to GitLab (--post flag not enabled)")


if __name__ == "__main__":
    main()
