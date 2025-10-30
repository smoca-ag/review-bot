# AI Code Reviewer for Git and GitLab

This tool leverages local AI models, via [Ollama](https://ollama.com/), to perform automated code reviews. It can analyze changes in **GitLab Merge Requests (MRs)** or review local **`git diff`** outputs, posting findings as inline comments or printing them to the console.

## Features

  - **Flexible Backends**: Works with remote GitLab MRs (`gitlab` backend) or local `git diff` outputs (`git` backend).
  - **Automated Analysis**: Fetches MR details and diffs from GitLab or generates them locally from your git repository.
  - **AI-Powered Review**: Uses a local AI model through Ollama to review code changes line-by-line.
  - **Context-Aware**: Provides the AI with the full context of the changes (MR title, full diff, file contents) before reviewing individual lines.
  - **Inline Commenting**: For the `gitlab` backend, it posts findings as actionable inline comments in the MR.
  - **Dry-Run Mode**: Allows you to see the review output in the console without posting to GitLab using the `--no-post` flag.
  - **Configurable**: Easily configure the GitLab token, Ollama URL, and model via environment variables.

-----

## Requirements

  - Python 3.8+
  - Git installed and available in your PATH.
  - A running instance of [Ollama](https://ollama.com/) with a suitable coding model (e.g., `qwen3-coder:30b`, `codellama`).
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
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    pip install .
    ```
    

3.  **Configure Environment Variables:**
    Create a `.env` file in the root of the project directory.

    ```env
    # .env file

    # Required only for the 'gitlab' backend
    GITLAB_API_TOKEN="your_gitlab_personal_access_token"

    # Optional Ollama configuration
    OPENAI_URL="http://localhost:11434/v1"
    OPENAI_MODEL="qwen3-coder:30b"
    OPENAI_API_KEY="unused-for-oolama"
    ```

-----

## Configuration

The script uses the following environment variables:

  - `GITLAB_API_TOKEN`: **Required for the `gitlab` backend only.** Your GitLab Personal Access Token. You can generate one from your GitLab profile under `Preferences > Access Tokens`. It needs the **`api` scope** to read MRs and post comments.
  - `OPENAI_URL` (Optional): The URL for your running Ollama or OpenAPI instance. **Defaults to** `http://localhost:11434/v1`.
  - `OPENAI_MODEL` (Optional): The name of the model to use. **Defaults to** `qwen3-coder:30b`. Ensure the model is downloaded first (`ollama pull <model_name>`).
  - `OPENAI_API_KEY` (Optional): API Key if you need one for LLM Access

-----

## Usage

The script's behavior is controlled by the `--backend` argument, which determines how the `spec` argument is interpreted.

### Arguments

  - `spec`: (Required) The target for the review.
      - For `gitlab` backend: The full URL of the Merge Request.
      - For `git` backend: A valid argument for the `git diff` command (e.g., a commit range like `main..HEAD` or a single commit like `HEAD~1` or a branch like `origin/main`).
  - `--backend`: (Optional) The backend to use. Choices are `gitlab` or `git`. **Defaults to `gitlab` if not specified.**
  - `--no-post`: (Optional) A flag to disable posting comments to GitLab. In `git` mode, output is always printed to the console, but this flag can prevent other side effects if any were added.

-----

### Example 1: Review a GitLab Merge Request

This command will review a specific GitLab MR and post comments.

```bash
python main.py --backend gitlab "https://gitlab.example.com/group/project/-/merge_requests/123"
```

To see the review in the console without posting, add `--no-post`:

```bash
python main.py --backend gitlab "https://gitlab.example.com/group/project/-/merge_requests/123" --no-post
```

-----

### Example 2: Review Local Git Changes

This command will review the changes between your current branch and the `main` branch. The review will be printed to your terminal.

```bash
# Make sure you are in the root directory of your git repository
python main.py --backend git "origin/main"
```

To review only the changes from the very last commit:

```bash
python main.py --backend git "HEAD~1"
```

-----

## How It Works

1.  **Select Backend**: The script initializes either the `Gitlab` or `Git` backend based on the `--backend` argument.
2.  **Fetch Data**:
      - **GitLab**: Connects to the GitLab API to fetch the MR title, diff, and the full content of changed files.
      - **Git**: Runs `git diff` and `git show` commands locally to get the diff and file contents.
3.  **Build Context**: Creates a comprehensive prompt for the AI, including the changes' title/summary and the complete diff. This helps the AI understand the overall goal.
4.  **Send Context**: The context is sent to the Ollama model in a persistent session, so the AI retains this information for subsequent questions.
5.  **Iterate and Review**: The script processes the diff line by line. For each **added** line of code, it asks the AI to review that line within the given context.
6.  **Parse and Display**: The AI's JSON response is parsed.
      - For both backends, findings are logged to the console.
      - For the `gitlab` backend (if not in `--no-post` mode), findings are posted as inline comments on the MR.

-----

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.