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
def backendFactory(backend):
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
    parser.add_argument('--no-post', action='store_true', help='Don\'t post, just show the review')
    parser.add_argument('--backend', type=str,choices=[backend.value for backend in BackendType], help='which backend to use, default to gitlab')

    args = parser.parse_args()
    # setup logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # Get configuration from environment variables
    ollama_model = os.getenv('OLLAMA_MODEL', 'qwen3-coder:30b')
    ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
    spec = args.spec


    prompts = Prompts(logger)
    ai_model = AI(ollama_url, ollama_model)
    mr_request = backendFactory(args.backend)(logger, spec)
    logger.info(f"Load the Merge Request {spec}")

    mr_request.load()

    diff_content = mr_request.diff()
    paths = paths_from_diff(diff_content)
    logger.info(f"Load the files {paths}")

    files = mr_request.get_files(paths)

    context_prompt = prompts.context_prompt(mr_request.title(), diff_content, files)


    logger.info(f"Send the context prompt")
    ai_model.question_persistent(context_prompt)

    logger.info(f"iterate over changes")
    for change_type, old_pos, new_pos, content, old_path, new_path in process_diff(diff_content):
        logger.info(f"{content}")
        if change_type != "added":
            continue
        if content.strip() == "":
            continue
        question = prompts.line_prompt(new_path, new_pos, content[1:])
        response = ai_model.question(question)
        try:
            json_response = json.loads(response)
            if len(json_response.get('issues', [])) == 0:
                continue
            logger.warning("".join([log_format_issue(issue) for issue in json_response["issues"]]))
            for issue in json_response.get('issues', []):
                if not args.no_post:
                    mr_request.post_review(issue, old_path, new_path, old_pos, new_pos)
        except json.decoder.JSONDecodeError as e:
            logger.error(f"Error loading response json from LLM: {e} {response}")


    # Post inline comments to GitLab
    if args.no_post:
        logger.info("Review generated but not posted to GitLab (--no-post flag enabled)")


if __name__ == "__main__":
    main()
