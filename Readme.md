
# AI Code Reviewer for GitLab

This tool leverages AI models, via [Ollama](https://ollama.com/), to perform automated code reviews on GitLab Merge Requests (MRs). 
It analyzes the code changes (diffs), identifies potential issues, and posts them as inline comments directly on the MR.

## Features

  - **Automated MR Analysis**: Fetches MR details and diffs directly from GitLab.
  - **AI-Powered Review**: Uses a local AI model through Ollama to review code changes line-by-line.
  - **Context-Aware**: Provides the AI with the full context of the MR (title, full diff, and file contents) before reviewing individual lines.
  - **Inline Commenting**: Posts findings as actionable inline comments in the GitLab MR.
  - **Dry-Run Mode**: Allows you to see the review output in the console without posting to GitLab using the `--no-post` flag.
  - **Configurable**: Easily configure the GitLab token, Ollama URL, and model via environment variables.

-----

## Requirements

  - Python 3.8+
  - A running instance of [Ollama](https://ollama.com/) with a suitable coding model (e.g., `qwen3-coder:30b`, `codellama`, `mistral`).
  - A GitLab Personal Access Token with `api` scope.

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
    pip install -r requirements.txt
    ```
    
3.  **Configure Environment Variables:**
    Create a `.env` file in the root of the project directory and add your configuration details.

    ```env
    # .env file
    PRIVATE_TOKEN="your_gitlab_personal_access_token"
    OLLAMA_URL="http://localhost:11434"
    OLLAMA_MODEL="qwen3-coder:30b"
    ```

-----

## Configuration

The script is configured using the following environment variables, which can be placed in a `.env` file:

  - `PRIVATE_TOKEN` ( **Required**): Your GitLab Personal Access Token. You can generate one from your GitLab profile under `Preferences > Access Tokens`. It needs the **`api` scope** to read MRs and post comments.
  - `OLLAMA_URL` (Optional): The URL for your running Ollama instance. **Defaults to** `http://localhost:11434`.
  - `OLLAMA_MODEL` (Optional): The name of the model to use from Ollama. **Defaults to** `qwen3-coder:30b`. Ensure the model is downloaded in Ollama (`ollama pull <model_name>`).

-----

## Usage

Run the script from your terminal, providing the URL of the GitLab Merge Request you want to review.

### Basic Command

```bash
python review-bot.py "https://gitlab.example.com/group/project/-/merge_requests/123"
```

### Dry-Run Mode

To generate a review and print it to the console without posting any comments to GitLab, use the `--no-post` flag. This is useful for testing and validation.

```bash
python review-bot.py "https://gitlab.example.com/group/project/-/merge_requests/123" --no-post
```

### Arguments

  - `merge_request_url`: (Required) The full URL of the GitLab Merge Request.
  - `--no-post`: (Optional) A flag to disable posting comments to GitLab.

-----

## How It Works

The script follows a logical sequence to perform the code review:

1.  **Parse URL**: Extracts the GitLab instance URL, project ID, and MR IID from the provided merge request URL.
2.  **Fetch Data**: Connects to the GitLab API using your private token to fetch the MR title, diff, and the full content of the changed files.
3.  **Build Context**: Creates a comprehensive "context prompt" for the AI, including the MR title and the complete diff. This initial prompt helps the AI understand the overall goal of the changes.
4.  **Send Context**: The context is sent to the Ollama model in a persistent session, so the AI retains this information for subsequent questions.
5.  **Iterate and Review**: The script processes the diff line by line. For each **added** line of code, it constructs a specific question for the AI, asking it to review that line within the given context.
6.  **Parse Response**: The AI is prompted to respond in a structured JSON format. The script parses this JSON to identify any issues.
7.  **Post Comments**: If not in dry-run mode, the script posts any identified issues as inline comments on the corresponding lines in the GitLab MR.

-----

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.