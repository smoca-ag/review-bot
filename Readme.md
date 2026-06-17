# AI Code Reviewer for Git and GitLab

This tool leverages AI models via [Pydantic AI](https://ai.pydantic.dev/) to perform automated, multi-agent code reviews. It can analyze changes in **GitLab Merge Requests (MRs)** or review local **`git diff`** outputs, posting findings as inline comments or printing them to the console. It also includes a webhook server to automatically trigger reviews on GitLab events.


## Features

  - **Flexible Backends**: Works with remote GitLab MRs (`gitlab` backend) or local `git diff` outputs (`git` backend).
  - **Multi-Agent Pipeline**: Six specialized sub-agents (context, security, logic, architecture, test, performance) review code sequentially, followed by a Critic agent that deduplicates and filters out false positives.
  - **Dependency Graph**: Parses imports and definitions across TypeScript/TSX, Ruby, Swift, Kotlin, and Python using tree-sitter, letting agents trace how changes ripple through the codebase.
  - **RAG Vector Index**: Builds an ephemeral ChromaDB index of the repository for semantic code search via the `semantic_code_search` tool.
  - **Structured Review Workflow**: Agents track findings through a 4-phase pipeline (Triage → Hypothesize → Falsify → Self-Critic) to reduce false positives.
  - **Sandboxed Tool Execution**: Agents fetch file contents, list directories, scan code, and execute shell commands inside an isolated Podman container.
  - **Inline Commenting**: For the `gitlab` backend, posts findings as actionable inline comments with precise line-number mapping (respecting renames).
  - **Webhook Server**: Automatically triggers reviews when a specific label is added or new commits are pushed to a GitLab MR. Supports review-all mode.
  - **Telemetry Support**: Export traces to an OpenTelemetry collector (via OTLP), with automatic console fallback when no endpoint is configured.
  - **Self-Improvement**: Agents can log tool and prompt improvement suggestions to `~/.review-bot/improvements.log`.
  - **Diff Preprocessing**: Large diffs and long lines are automatically truncated (governed by `MAX_LINES` / `MAX_LINE_LENGTH`), with line numbers injected for precise issue location.

-----

## Requirements

  - Python 3.11+
  - Git installed and available in your PATH.
  - [Podman](https://podman.io/) installed and running. On macOS, run `podman machine start` before first use. The sandbox container is built automatically at runtime from `review-container/Dockerfile`.
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
    pip install -e ".[dev]"
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

    # Alternatively, use Anthropic (set ANTHROPIC_API_KEY as well)
    # ANTHROPIC_DEFAULT_OPUS_MODEL="claude-3-7-sonnet-latest"
    # ANTHROPIC_API_KEY="your_anthropic_api_key"

    # Optional: OpenTelemetry tracing (falls back to console if unset)
    # OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
    # DISABLE_TELEMETRY="true"  # Set to disable all tracing

    # Optional: Diff truncation limits
    # MAX_LINES="200"          # Max lines per file in diff
    # MAX_LINE_LENGTH="150"    # Max characters per diff line

    # Optional: Agent limits
    # AGENT_REQUEST_LIMIT="200"      # Max API requests per agent run
    # CONFIDENCE_THRESHOLD="0.9"     # Min confidence for inline comments

    # Webhook server configuration (if using review-bot-gitlab-webhook)
    # GITLAB_WEBHOOK_TOKEN="your_secret_webhook_token"  # REQUIRED for webhook
    # WEBHOOK_HOST="0.0.0.0"
    # WEBHOOK_PORT="8080"
    # GITLAB_WEBHOOK_LABEL="ai-review-requested"
    # GITLAB_WEBHOOK_REVIEW_ALL="false"
    # MAX_PARALLEL_REVIEWS="3"    # Max concurrent reviews, 0 = unlimited
    ```

-----

## Configuration

The script uses the following environment variables:

  - `GITLAB_API_TOKEN`: **Required for the `gitlab` backend only.** Your GitLab Personal Access Token with **`api` scope**.
  - `OPENAI_URL` (Optional): URL for your OpenAI-compatible instance. **Defaults to** `http://localhost:11434/v1`.
  - `OPENAI_MODEL` (Optional): Model name. **Defaults to** `qwen3-coder:30b`.
  - `OPENAI_API_KEY` (Optional): API key for model access.
  - `ANTHROPIC_DEFAULT_OPUS_MODEL` (Optional): If set, uses the Anthropic provider with this model. Requires `ANTHROPIC_API_KEY`.
  - `ANTHROPIC_API_KEY` (Optional): API key for Anthropic provider.
  - `OTEL_EXPORTER_OTLP_ENDPOINT` (Optional): OTLP HTTP endpoint for trace export. Falls back to console output if unset.
  - `DISABLE_TELEMETRY` (Optional): Set to `true` to disable all OpenTelemetry tracing. **Defaults to** `false`.
  - `AGENT_REQUEST_LIMIT` (Optional): Max API requests per agent run. **Defaults to** `200`.
  - `CONFIDENCE_THRESHOLD` (Optional): Minimum confidence score (0.0–1.0) for posting inline comments. **Defaults to** `0.9`.
  - `MAX_LINES` (Optional): Max lines per file displayed in the diff before truncation. **Defaults to** `200`.
  - `MAX_LINE_LENGTH` (Optional): Max characters per diff line before truncation. **Defaults to** `150`.
  - `GITLAB_WEBHOOK_TOKEN` (Optional for CLI, **required** for webhook server): Secret token validated via HMAC on incoming webhook requests.
  - `WEBHOOK_HOST` (Optional): Webhook server bind address. **Defaults to** `0.0.0.0`.
  - `WEBHOOK_PORT` (Optional): Webhook server port. **Defaults to** `8080`.
  - `GITLAB_WEBHOOK_LABEL` (Optional): Label that triggers a review. **Defaults to** `ai-review-requested`.
  - `GITLAB_WEBHOOK_REVIEW_ALL` (Optional): If `true`, triggers on all MR opens and new commits regardless of label. **Defaults to** `false`.
  - `MAX_PARALLEL_REVIEWS` (Optional): Maximum concurrent reviews the webhook server will run. `0` means unlimited. **Defaults to** `3`.

-----

## Usage

The project provides two main executable scripts: `review-bot` (manual reviews) and `review-bot-gitlab-webhook` (automated reviews).

### `review-bot`

```bash
usage: review-bot [-h] [--post] [--backend {gitlab,git}] spec

AI Code Review for GitLab Merge Requests

positional arguments:
  spec                  Full Merge Request url or an argument for git diff

options:
  -h, --help            show this help message and exit
  --post                Post the review directly to the merge request
  --backend {gitlab,git}
                        Which backend to use (default: gitlab)
```

#### Example 1: Review a GitLab Merge Request

Print findings to the console:

```bash
review-bot --backend gitlab "https://gitlab.example.com/group/project/-/merge_requests/123"
```

Post findings as inline comments on the MR (confidence ≥ 0.9, non-minor severity only; existing bot comments are updated on re-review):

```bash
review-bot --backend gitlab "https://gitlab.example.com/group/project/-/merge_requests/123" --post
```

#### Example 2: Review Local Git Changes

Review changes between your current branch and `main`:

```bash
review-bot --backend git "origin/main"
```

Review only the last commit:

```bash
review-bot --backend git "HEAD~1"
```

### `review-bot-gitlab-webhook`

Starts an HTTP server that listens for GitLab webhook events and automatically triggers reviews.

```bash
# GITLAB_WEBHOOK_TOKEN is required — the server will exit with FATAL if unset
review-bot-gitlab-webhook
```

The webhook processes only `merge_request` events and triggers a review when:
  1. The configured label (default: `ai-review-requested`) is added to the Merge Request.
  2. New commits are pushed to the Merge Request (and the label is already present).
  3. The Merge Request is opened or reopened (and the label is already present).

Draft/WIP MRs and already-merged MRs are skipped. If `GITLAB_WEBHOOK_REVIEW_ALL` is set to `true`, reviews trigger on all MR opens and new commits regardless of labels.

The server also responds to `GET` requests for health checks.

-----

## How It Works

  1.  **Backend Selection**: The script initializes either the `Gitlab` or `Git` backend based on the `--backend` argument.
  2.  **Repository Setup**: The backend clones the repo (shallow clone for GitLab) and checks out the relevant branch into a temporary directory.
  3.  **Sandbox Initialization**: A Podman container is built from `review-container/Dockerfile` and started with the repository mounted at `/workspace`. The container includes Python 3, Node.js, Ruby (with Rails), Java/Maven, Android SDK (SDK 34, build-tools 34.0.0, NDK 26.1), and Gradle 8.10.2.
  4.  **Dependency Graph**: The repo is parsed with tree-sitter to build an import/definition graph for TypeScript/TSX, Ruby, Swift, Kotlin, and Python, enabling agents to understand cross-file dependencies.
  5.  **RAG Index**: An ephemeral ChromaDB vector index is built over all source files (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.rb`, `.swift`, `.kt`, etc.) for semantic code search.
  6.  **Diff Preprocessing**: The diff is truncated to `MAX_LINES` per file and `MAX_LINE_LENGTH` per line. Line numbers are injected for precise issue location.
  7.  **Multi-Agent Execution**: Six specialized sub-agents run **sequentially** (for shared prefix cache optimization) in this order: **context** → **security** → **logic** → **architecture** → **test** → **performance**. Each agent has access to 9 tools for gathering context from the sandbox.
  8.  **Critic Review**: The Critic agent consolidates all sub-agent reports. It ruthlessly filters out:
        - Findings with confidence < 0.7
        - Findings with counter-arguments shorter than 20 characters
        - Findings with empty or vague falsification methods
        - Inconclusive findings unless risk_score ≥ 4 and confidence ≥ 0.8
        - All positive feedback or praise
      Suspect findings are spot-checked by re-running tool calls.
  9.  **Output**: The final, filtered findings are parsed.
        - A markdown summary is logged to the console.
        - If `--post` is used with the `gitlab` backend, a top-level MR comment is posted, plus inline line comments for findings with confidence ≥ `CONFIDENCE_THRESHOLD` (default 0.9) and non-minor severity.
  10. **Cleanup**: The Podman container is destroyed and the temporary repo directory is removed. Telemetry spans cover the entire pipeline.

-----

## Agent Tools

Each sub-agent has access to these 9 tools:

| Tool | Description |
|---|---|
| `read_file` | Read a file from the sandbox (`podman exec cat`) |
| `list_files` | List directory contents (`podman exec ls -la`) |
| `search_code` | Search code for patterns (`podman exec grep -rn`) |
| `execute_command` | Run arbitrary shell commands (60s timeout) |
| `semantic_code_search` | Semantic code search over the ChromaDB RAG index |
| `view_code_diff_section` | Filter and paginate through specific sections of the diff |
| `dependency_graph` | Query which files import or are imported by a given module |
| `update_todo` | Track findings through the 4-phase workflow (Triage → Hypothesize → Falsify → Self-Critic) |
| `suggest_bot_improvement` | Log a tool or prompt improvement suggestion to `~/.review-bot/improvements.log` |

-----

## Supported Languages

The dependency graph parser supports these languages for cross-file import/definition analysis:

  - TypeScript / TSX
  - Ruby
  - Swift
  - Kotlin
  - Python

The RAG index additionally indexes: JavaScript, Go, Rust, Java, C/C++, Ruby, PHP, Scala, Shell, YAML, TOML, JSON, and Markdown.

-----

## Testing

```bash
# Run all tests
python -m unittest discover -s tests

# Run a specific test suite
python -m unittest tests.test_text_utils

# Note: test_tools_e2e.py requires Podman to be running
```

### Tool Schema Generation (`test_native_llm_tools/`)

When agent tools use names, descriptions, or parameter schemas that feel unnatural to the model, the model invokes them less effectively. To keep tool schemas aligned with what the model would naturally generate, the scripts in `test_native_llm_tools/` send multiple natural-language descriptions of each tool to the local model and ask it to produce the ideal JSON function definition.

```bash
# Run all tool schema tests
./test_native_llm_tools/run_all.sh

# Run a single tool test
./test_native_llm_tools/test_read_file.sh
```

Each script outputs 5 candidate JSON schemas. Use the results to adjust function names, docstrings, and parameter signatures in the corresponding `review_bot/tools/*.py` file.

-----

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
