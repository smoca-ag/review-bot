# AI Code Reviewer for Git and GitLab

This tool leverages AI models via [Pydantic AI](https://ai.pydantic.dev/) to perform automated, multi-agent code reviews. It can analyze changes in **GitLab Merge Requests (MRs)** or review local **`git diff`** outputs, posting findings as inline comments or printing them to the console. It also includes a webhook server to automatically trigger reviews on GitLab events.

## Features

  - **Flexible Backends**: Works with remote GitLab MRs (`gitlab` backend) or local `git diff` outputs (`git` backend).
  - **Multi-Agent Architecture**: Uses specialized sub-agents (Security, Logic, Architecture, Context, QA, Performance) to review code concurrently, followed by a Critic agent that consolidates and filters out false positives.
  - **Sandboxed Tool Execution**: The agents can fetch file contents, list directories, scan code, and execute shell commands inside an isolated Podman container to gather context safely.
  - **Inline Commenting**: For the `gitlab` backend, it posts findings as actionable inline comments in the MR.
  - **Webhook Server**: Automatically trigger reviews when a specific label is added or new commits are pushed to a GitLab MR.
  - **Telemetry Support**: Export traces to an OpenTelemetry collector (via OTLP) to monitor the agent execution.
  - **Configurable**: Easily configure the GitLab token, AI model URL, and model via environment variables.

-----

## Requirements

  - Python 3.11+
  - Git installed and available in your PATH.
  - [Podman](https://podman.io/) installed and running (used by the agents to safely execute commands and read files from the repository).
  - An AI model provider (e.g., Anthropic, OpenAI, or a local instance of [Ollama](https://ollama.com/)).
  - For the `gitlab` backend: A GitLab Personal Access Token with `api` scope.

-----

## Installation

1.  **Clone the repository:**

    ```bash
    git clone <your-repository-url>
    cd <your-repository-directory>
    ```

2.  **Install Python dependencies:**
    It's recommended to use a virtual environment.

    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
    pip install -e .
    ```
    

3.  **Configure Environment Variables:**
    Create a `.env` file in the root of the project directory.

    ```env
    # .env file

    # Required only for the 'gitlab' backend
    GITLAB_API_TOKEN="your_gitlab_personal_access_token"

    # Model configuration
    OPENAI_URL="http://localhost:11434/v1"
    OPENAI_MODEL="qwen3-coder:30b"
    OPENAI_API_KEY="unused-for-ollama"
    
    # Alternatively, use Anthropic
    # ANTHROPIC_DEFAULT_OPUS_MODEL="claude-3-7-sonnet-latest"
    # ANTHROPIC_API_KEY="your_anthropic_api_key"

    # Optional: OpenTelemetry tracing
    # OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"

    # Webhook server configuration (if using review-bot-gitlab-webhook)
    # WEBHOOK_HOST="0.0.0.0"
    # WEBHOOK_PORT="8080"
    # GITLAB_WEBHOOK_LABEL="ai-review-requested"
    # GITLAB_WEBHOOK_REVIEW_ALL="false"
    # GITLAB_WEBHOOK_TOKEN="your_secret_webhook_token"
    ```

-----

## Configuration

The script uses the following environment variables:

  - `GITLAB_API_TOKEN`: **Required for the `gitlab` backend only.** Your GitLab Personal Access Token. You can generate one from your GitLab profile under `Preferences > Access Tokens`. It needs the **`api` scope** to read MRs and post comments.
  - `OPENAI_URL` (Optional): The URL for your running OpenAI-compatible instance (e.g. Ollama). **Defaults to** `http://localhost:11434/v1`.
  - `OPENAI_MODEL` (Optional): The name of the model to use. **Defaults to** `qwen3-coder:30b`.
  - `OPENAI_API_KEY` (Optional): API Key if you need one for LLM Access.
  - `ANTHROPIC_DEFAULT_OPUS_MODEL` (Optional): If set, the bot will use the Anthropic provider with this model instead of OpenAI.
  - `OTEL_EXPORTER_OTLP_ENDPOINT` (Optional): An OTLP HTTP endpoint to send traces to (e.g. `http://localhost:4318/v1/traces`).

-----

## Usage

The project provides two main executable scripts: `review-bot` (for manual reviews) and `review-bot-gitlab-webhook` (for automated reviews).

### `review-bot`

The script's behavior is controlled by the `--backend` argument, which determines how the `spec` argument is interpreted.

```bash
usage: review-bot [-h] [--post] [--backend {gitlab,git}] spec

AI Code Review for GitLab Merge Requests

positional arguments:
  spec                  Full Merge Request url or a argument for git diff

options:
  -h, --help            show this help message and exit
  --post                Post the review directly to the merge request
  --backend {gitlab,git}
                        which backend to use, default to gitlab
```

#### Example 1: Review a GitLab Merge Request

This command will review a specific GitLab MR and print findings to the console.

```bash
review-bot --backend gitlab "https://gitlab.example.com/group/project/-/merge_requests/123"
```

To automatically post the findings as comments on the MR, add `--post`:

```bash
review-bot --backend gitlab "https://gitlab.example.com/group/project/-/merge_requests/123" --post
```

#### Example 2: Review Local Git Changes

This command will review the changes between your current branch and the `main` branch. The review will be printed to your terminal.

```bash
# Make sure you are in the root directory of your git repository
review-bot --backend git "origin/main"
```

To review only the changes from the very last commit:

```bash
review-bot --backend git "HEAD~1"
```

### `review-bot-gitlab-webhook`

This script starts an HTTP server that listens for GitLab webhook events. It automatically triggers the review process when specific conditions are met.

```bash
# Ensure GITLAB_WEBHOOK_TOKEN is set in your environment
review-bot-gitlab-webhook
```

The webhook triggers a review when:
1. The configured label (default: `ai-review-requested`) is added to the Merge Request.
2. New commits are pushed to the Merge Request (and the label is already present).
3. The Merge Request is opened or reopened (and the label is already present).

If `GITLAB_WEBHOOK_REVIEW_ALL` is set to `true`, it will trigger on all new commits and MR opens, regardless of labels.

-----

## How It Works

1.  **Select Backend**: The script initializes either the `Gitlab` or `Git` backend based on the `--backend` argument.
2.  **Sandbox Initialization**: A Podman container is created, and the repository is mounted into it. This allows the AI agents to safely execute shell commands and read files.
3.  **Multi-Agent Execution**: Six specialized sub-agents (Security, Logic, Architecture, Context, QA, Performance) are launched concurrently. They analyze the PR description and code diff, using tools to fetch additional context from the repository if needed.
4.  **Critic Review**: The findings from all sub-agents are passed to a Critic agent. The Critic consolidates the reports, filters out duplicates, and ruthlessly drops false positives or low-confidence findings.
5.  **Output**: The final, filtered findings are parsed.
      - For both backends, findings are logged to the console.
      - For the `gitlab` backend (if `--post` is provided), findings are posted as inline comments on the MR.
6.  **Cleanup**: The Podman container is destroyed.

-----

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
