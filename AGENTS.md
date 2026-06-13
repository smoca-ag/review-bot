# Review Bot – Architecture Reference

AI-powered code review bot built with [Pydantic AI](https://ai.pydantic.dev/). Reviews GitLab Merge Requests or local git diffs using a multi-agent pipeline, posts findings as inline comments.

## Prerequisites

- Python 3.11+
- [Podman](https://podman.io/) (on macOS: `podman machine start`; container built from `review-container/Dockerfile`)
- For `gitlab` backend: GitLab Personal Access Token with `api` scope

## Development Commands

```bash
# One-time setup
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run tests
python -m unittest discover -s tests

# Type check
mypy review_bot/
```

## Code Style

- Imports: standard library → third-party → local (`review_bot.*`), each group separated by a blank line
- Docstrings: Google-style (`Args:`, `Returns:`, `Raises:`)
- Type hints: Python 3.10+ union syntax (`str | None`) — do NOT use `Optional[str]`
- Module-level docstring at top of each file describing the module's purpose

## Entry Points

| Command | Module | Purpose |
|---|---|---|
| `review-bot` | `review_bot.cli:main` | Manual review of a GitLab MR or local git diff |
| `review-bot-gitlab-webhook` | `review_bot.gitlab_webhook:main` | HTTP webhook server; auto-triggers reviews on GitLab events |

## Core Flow (`review_bot.review_bot:review`)

1. **Backend factory** (`review_bot.__init__.py:backend_factory`) instantiates `Gitlab` or `Git` based on `--backend` flag.
2. Backend's `load()` fetches MR metadata, diffs, and checks out the repo into a temp directory.
3. `setup_container()` spins up a Podman sandbox (`review-container/Dockerfile`) with the repo mounted at `/workspace`.
4. **RAG index** (`review_bot.rag:build_vector_index`): walks the repo, chunks source files, loads into an ephemeral ChromaDB collection for semantic search.
5. **Agent orchestration** (`async_review_process`):
   - 6 sub-agents run **sequentially** (shared prefix cache optimization):
     - `context` – validates PR description, purpose, test plan
     - `security` – XSS, SQLi, auth bypass, secrets
     - `logic` – logic bugs, type errors, unhandled exceptions
     - `architecture` – SOLID, DRY, coupling violations
     - `test` – coverage gaps, edge cases, race conditions
     - `performance` – N+1 queries, memory leaks, Big-O issues
   - Critic agent consolidates all `SubAgentReport`s → `FinalReviewResult`, deduplicates, drops low-confidence findings (< 0.7), strips positive feedback.
6. **Output** (`review_bot.formatter:format_and_post_review`):
   - Logs markdown summary to console.
   - If `--post`, posts a top-level MR comment + inline line comments (confidence ≥ 0.9, non-minor severity) via GitLab Discussions API.
7. **Cleanup**: kills Podman container, removes temp repo directory.

## Component Map

```
review_bot/
├── __init__.py          BackendType enum, backend_factory()
├── cli.py               CLI entry point, argparse → review()
├── config.py            Model resolution (OpenAI / Anthropic), dotenv, telemetry bootstrap
├── review_bot.py        Core orchestration: container, RAG, agent pipeline, cleanup
├── models.py            Pydantic schemas: ReviewDeps, LineComment, SubAgentReport, FinalReviewResult
├── agents/              Agent definitions (AgentDef: name, output_type, specialty_prompt)
│   ├── __init__.py      SUB_AGENTS list + critic_agent_def
│   ├── context.py       PR description evaluator
│   ├── security.py      Vulnerability scanner
│   ├── logic.py         Bug finder
│   ├── architecture.py  Design reviewer
│   ├── test.py          QA & coverage reviewer
│   ├── performance.py   Scalability reviewer
│   └── critic.py        Consolidator & gatekeeper
├── backend/             Data access layer
│   ├── base_backend.py  Abstract: container mgmt, file ops, command exec, cleanup
│   ├── gitlab.py        GitLab API: MR fetch, diff, discussions, inline comments, repo checkout
│   └── git.py           Local git diff (uses cwd as repo_dir)
├── tools.py             Shared agent tools (fetch_file, list_files, scan_code, execute_command, vector_search, suggest_bot_improvement)
├── rag.py               ChromaDB vector index builder
├── text_utils.py        Diff parsing, line injection, truncation, pagination, CDATA wrapping
├── formatter.py         Markdown review generation, inline comment posting
├── gitlab_webhook.py    HTTP webhook server, ReviewManager (queue + process pool)
├── telemetry.py         OpenTelemetry setup (OTLP / console exporter)
└── meta_feedback.py     (if present) meta-feedback collection
```

## Sandboxed Tool Execution

All agent tools delegate to the backend's Podman container (`base_backend.py`):
- `fetch_file_content` → `podman exec cat <file>`
- `list_files` → `podman exec ls -la`
- `scan_code` → `podman exec grep -rn`
- `execute_command` → `podman exec /bin/sh -c "<command>"` (60s timeout)
- `vector_search` → ChromaDB collection query
- `suggest_bot_improvement` → appends JSON to `~/.review-bot/improvements.log`

## Agent Tooling (`review_bot.tools.py`)

Tools are defined as `pydantic_ai.Tool` wrapping plain functions. Each receives `RunContext[ReviewDeps]` giving access to `mr_request`, `mr_description`, and `vector_index`.

## Webhook Server (`review_bot.gitlab_webhook.py`)

- `ThreadingHTTPServer` on configurable `WEBHOOK_HOST:WEBHOOK_PORT`
- Validates `X-Gitlab-Token` header via HMAC
- `ReviewManager`: single-worker queue; cancels in-flight review if new event arrives for same MR
- Triggers on: label added, new commits (with label), MR open/reopen (with label). `GITLAB_WEBHOOK_REVIEW_ALL=true` bypasses label requirement.

## Configuration (Environment Variables)

| Variable | Purpose |
|---|---|
| `GITLAB_API_TOKEN` | GitLab Personal Access Token (api scope) |
| `OPENAI_URL` | OpenAI-compatible endpoint (default `http://localhost:11434/v1`) |
| `OPENAI_MODEL` | Model name (default `qwen3-coder:30b`) |
| `OPENAI_API_KEY` | API key for model provider |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | If set, use Anthropic provider instead |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP endpoint for trace export |
| `DISABLE_TELEMETRY` | Set `true` to disable all tracing |
| `WEBHOOK_HOST` / `WEBHOOK_PORT` | Webhook server bind address |
| `GITLAB_WEBHOOK_LABEL` | Label that triggers review (default `ai-review-requested`) |
| `GITLAB_WEBHOOK_REVIEW_ALL` | Bypass label requirement (`true`/`false`) |
| `GITLAB_WEBHOOK_TOKEN` | Secret token for webhook validation |
| `CONFIDENCE_THRESHOLD` | Min confidence for inline comments (default `0.9`) |
| `AGENT_REQUEST_LIMIT` | Max API requests per agent run (default `200`) |
| `MAX_LINES` / `MAX_LINE_LENGTH` | Diff truncation limits (default `200` / `150`) |

## Testing

```bash
python -m unittest discover -s tests
```

Tests in `tests/` cover `text_utils` utilities and end-to-end tool execution. CI runs via GitLab CI (`.gitlab-ci.yml`) with Podman available.

## Key Design Decisions

- **Sequential sub-agent execution** (not parallel) to maximize LLM prefix cache hits — all agents share the same system prompt, differing only in the appended specialty prompt suffix.
- **Critic as gatekeeper** — sub-agents are permissive; the critic ruthlessly filters false positives, enforces confidence thresholds, and strips all positive feedback.
- **Podman sandbox** — agents execute commands in an isolated container to safely run linters, tests, and arbitrary code against the reviewed repo.
- **Ephemeral RAG** — ChromaDB index is built in-memory per review; no persistent storage.
- **Diff coordinate resolution** (`text_utils.resolve_diff_coordinates`) maps new-file line numbers back to old-file coordinates for accurate GitLab inline comments, handling renames.
