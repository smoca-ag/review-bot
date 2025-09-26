import requests
import sys
import json
import os
from dotenv import load_dotenv
import argparse
import logging

from lib.ai import AI
from lib.gitlab import Gitlab
from lib.prompts import Prompts
from lib.diff import process_diff, paths_from_diff

def main():
    # Set up command line argument parser
    load_dotenv()

    parser = argparse.ArgumentParser(description='AI Code Review for GitLab Merge Requests')
    parser.add_argument('project_id', type=int, help='GitLab Project ID')
    parser.add_argument('merge_request_id', type=int, help='Merge Request ID')
    parser.add_argument('--no-post', action='store_true', help='Don\'t post to GitLab, just show the review')

    args = parser.parse_args()
    # setup logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # Get configuration from environment variables
    gitlab_url = os.getenv('GITLAB_URL')
    private_token = os.getenv('PRIVATE_TOKEN')
    ollama_model = os.getenv('OLLAMA_MODEL', 'qwen3-coder:30b')
    ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')

    # Validate environment variables
    if not gitlab_url:
        logger.error("Error: GITLAB_URL environment variable is required")
        sys.exit(1)

    if not private_token:
        logger.error("Error: PRIVATE_TOKEN environment variable is required")
        sys.exit(1)

    project_id = args.project_id
    merge_request_iid = args.merge_request_id


    prompts = Prompts(logger)
    ai_model = AI(ollama_url, ollama_model)
    mr_request = Gitlab(logger, gitlab_url, private_token, project_id, merge_request_iid)
    logger.info(f"Load the Merge Request {merge_request_iid}")

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
        if change_type != "added":
            continue
        if content.strip() == "":
            continue
        logger.info(f"Processing change {change_type} at {old_pos} to {new_pos} for path {new_path} from {old_path} and content {content}")
        question = prompts.line_prompt(new_path, new_pos, content)
        response = ai_model.question(question)
        logger.info(f"review response: {response}")
        try:
            json_response = json.loads(response)
            for issue in json_response.get('issues', []):
                if not args.no_post:
                    mr_request.post_review(issue, old_path, new_path, old_pos, new_pos)


        except json.decoder.JSONDecodeError as e:
            logger.error(f"Error parsing response from GitLab: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error posting inline comment to GitLab: {e}")


    # Post inline comments to GitLab
    if args.no_post:
        logger.info("Review generated but not posted to GitLab (--no-post flag enabled)")


if __name__ == "__main__":
    main()
