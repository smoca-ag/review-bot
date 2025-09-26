# AI Code Reviewer for GitLab

This Python script leverages a local AI model via [Ollama](https://ollama.com/) 
to perform automated code reviews on GitLab Merge Requests (MRs). It analyzes the changes (diffs) in an MR, s
ends the code to an AI model for feedback, and posts the AI's findings as inline comments directly on the merge request.

-----

## Features

  - **GitLab Integration**: Fetches merge request details, diffs, and file contents directly from the GitLab API.
  - **AI-Powered Review**: Uses a local Ollama-compatible large language model to analyze code for potential issues, bugs, or style violations.
  - **Inline Commenting**: Posts review comments directly on the relevant lines of code within the GitLab MR.
  - **Context-Aware**: Provides the AI with the full context of the MR (title, diff, and full files) before asking for a line-by-line review.
  - **Flexible & Local**: Runs with any Ollama model, keeping your code on your own infrastructure.
  - **Dry-Run Mode**: Allows you to generate a review and see the output in your console without posting it to GitLab using the `--no-post` flag.

-----

## Prerequisites

Before you begin, ensure you have the following installed and configured:

  - **Python 3.8+**
  - **GitLab Account**: A GitLab account with access to the target project.
  - **GitLab Personal Access Token**: A [Personal Access Token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html) with `api` scope to allow the script to interact with your project.
  - **Ollama**: An instance of [Ollama](https://ollama.com/) running with a suitable model for code review (e.g., `codellama`, `qwen2-coder`, etc.).

-----

## Installation & Setup

1.  **Clone the Repository**

    ```bash
    git clone <your-repository-url>
    cd <your-repository-name>
    ```

2.  **Install Dependencies**
    It's recommended to use a virtual environment.

    ```bash
    # Create and activate a virtual environment (optional but recommended)
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

    # Install the required Python packages
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables**
    Create a file named `.env` in the root of the project directory and add the following configuration. This file stores your credentials and settings securely.

    ```ini
    # .env file

    # Your GitLab instance URL (e.g., https://gitlab.com)
    GITLAB_URL="https://gitlab.com"

    # Your GitLab Personal Access Token with API scope
    PRIVATE_TOKEN="your_private_gitlab_token"

    # The Ollama model to use for the review
    OLLAMA_MODEL="qwen2-coder:34b"

    # The URL of your running Ollama instance
    OLLAMA_URL="http://localhost:11434"
    ```

-----

## Usage

Run the script from your terminal, providing the `Project ID` and `Merge Request IID` as arguments.

### Basic Command

```bash
python main.py <PROJECT_ID> <MERGE_REQUEST_IID>
```

  - `<PROJECT_ID>`: The numeric ID of your project in GitLab. You can find this on the project's main page.
  - `<MERGE_REQUEST_IID>`: The "internal" ID of the merge request (e.g., `!123`). This is the number you see in the GitLab UI, not the global ID.

### Example

To review merge request `!42` in project `12345`:

```bash
python main.py 12345 42
```

### Dry-Run Mode

To run the script and see the generated review comments in the console without posting them to GitLab, use the `--no-post` flag. This is useful for testing and debugging.

```bash
python main.py 12345 42 --no-post
```

-----

## How It Works

The script follows a straightforward process:

1.  **Initialization**: It parses command-line arguments and loads the configuration from the `.env` file.
2.  **Fetch MR Data**: It connects to the GitLab API to fetch the merge request's title, diff, and the full content of all changed files.
3.  **Provide Context to AI**: A "context prompt" containing the MR title, the complete diff, and the contents of the changed files is sent to the Ollama model. This gives the AI a high-level understanding of the changes.
4.  **Line-by-Line Review**: The script then iterates through each **added** line in the diff.
5.  **Generate Feedback**: For each added line, it sends a specific prompt to the AI, asking it to review that line within the context of its file.
6.  **Parse Response**: The AI is expected to respond with a JSON object containing a list of issues. The script parses this response.
7.  **Post Comments**: For each issue found by the AI, the script posts an inline comment to the corresponding line in the GitLab merge request (unless `--no-post` is enabled).