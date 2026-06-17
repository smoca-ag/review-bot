# Review Bot – Architecture Reference

AI-powered code review bot built with [Pydantic AI](https://ai.pydantic.dev/). Reviews GitLab Merge Requests or local git diffs using a multi-agent pipeline, posts findings as inline comments.

## Code Style

- Imports: standard library → third-party → local (`review_bot.*`), each group separated by a blank line
- Docstrings: Google-style (`Args:`, `Returns:`, `Raises:`)
- Type hints: Python 3.10+ union syntax (`str | None`) — do NOT use `Optional[str]`
- Module-level docstring at top of each file describing the module's purpose
- Build system: `pyproject.toml` only (no `setup.py`, no `setup.cfg`). Dependencies, entry points, and `mypy` config all live there.
- The codebase is **primarily async** (`asyncio`). CLI entry (`cli.py:main`), the agent pipeline (`pipeline.py`), and tool calls are all `async def`.

## For AI Assistants

**When you add or remove an environment variable**, update both the `Configuration` table below and the `Configuration` section and `.env` example in `README.md`.

**When you add or change a key design decision**, add it to the `Key Design Decisions` section below and keep it up to date.

Only 4 files live at `review_bot/` — read them first as a table of contents:

| File | What it tells you |
|---|---|
| `__init__.py` | Public API: `review()`, `BackendType`, `backend_factory()` |
| `cli.py` | CLI argument parsing → calls `review()` |
| `gitlab_webhook.py` | Webhook server and `ReviewManager` queue |
| `config.py` | Environment config, model resolution, constants |

Navigate by concern:
- "How does review flow work?" → `orchestration/`
- "What data shapes exist?" → `models/`
- "How do agents talk to the repo?" → `tools/` → `backend/container_manager.py`

## Entry Points

| Command | Module | Purpose |
|---|---|---|
| `review-bot` | `review_bot.cli:main` | Manual review of a GitLab MR or local git diff |
| `review-bot-gitlab-webhook` | `review_bot.gitlab_webhook:main` | HTTP webhook server; auto-triggers reviews on GitLab events |

## Core Flow

1. **Backend loads the diff**: `backend_factory()` creates `Gitlab` or `Git`; `load()` fetches MR metadata + diffs, checks out repo into a temp dir.
2. **Orchestration**: `orchestration/orchestrator.py:review()` sets up the sandbox + RAG, then runs the multi-agent pipeline.
3. **Multi-agent pipeline**: 6 sub-agents run sequentially (`context` → `security` → `logic` → `architecture` → `test` → `performance`), then a critic consolidates results, drops confidence < 0.7, and strips positive feedback.
4. **Output + cleanup**: Markdown summary logged to console; optionally posts top-level comment + inline comments (confidence ≥ 0.9) via GitLab API. Container and temp dir are destroyed.

## Component Map

```
review_bot/
├── __init__.py            Public API: BackendType, backend_factory(), review()
├── cli.py                 CLI entry point
├── gitlab_webhook.py      Webhook server + ReviewManager queue
├── config.py              Model resolution, env loading, constants
│
├── models/                ReviewDeps (dataclass), AgentDef (dataclass), Pydantic schemas (LineComment, SubAgentReport, etc.)
├── orchestration/         Pipeline execution: agents, prompts, formatting, top-level review()
├── agents/                AgentDef definitions: context, security, logic, architecture, test, performance, critic
├── backend/               Data access: Git, Gitlab, ContainerManager, GitlabReviewPoster
├── tools/                 9 pydantic_ai.Tool definitions: diff_context, fetch_file_content, list_files, scan_code, execute_command, dependency_graph, vector_search, suggest_bot_improvement, update_todo
├── graph/                 Dependency graph engine via tree-sitter (TS/TSX, Ruby, Swift, Kotlin, Python)
├── rag/                   Ephemeral ChromaDB vector index (create_vector_index, build_vector_index)
├── utils/                 Diff utilities (DiffHunk, truncation, coordinate resolution) and text helpers
└── infra/                 OpenTelemetry setup
```

## Sandboxed Tool Execution

All agent tools delegate to `ContainerManager` (`backend/container_manager.py`), which runs commands in the Podman sandbox:
- `fetch_file_content` → `podman exec cat <file>`
- `list_files` → `podman exec ls -la`
- `scan_code` → `podman exec grep -rn`
- `execute_command` → `podman exec /bin/sh -c "<command>"` (60s timeout)

`vector_search` queries ChromaDB locally; `suggest_bot_improvement` appends JSON to `~/.review-bot/improvements.log`.

Tools receive `RunContext[ReviewDeps]` giving access to `mr_request`, `mr_description`, `container_manager`, and `vector_index`.

## Webhook Server

- `ThreadingHTTPServer` on `WEBHOOK_HOST:WEBHOOK_PORT`; validates `X-Gitlab-Token` via HMAC.
- `ReviewManager`: queue + `multiprocessing.Process` workers (up to `MAX_PARALLEL_REVIEWS`), cancels in-flight review on new event for same MR.
- Triggers on: label added, new commits (with label), MR open/reopen (with label). `GITLAB_WEBHOOK_REVIEW_ALL=true` bypasses label requirement.

## Configuration (Environment Variables)

| Variable | Purpose |
|---|---|
| `GITLAB_API_TOKEN` | GitLab Personal Access Token (api scope) |
| `OPENAI_URL` | OpenAI-compatible endpoint (default `http://localhost:11434/v1`) |
| `OPENAI_MODEL` | Model name (default `qwen3-coder:30b`) |
| `OPENAI_API_KEY` | API key for model provider |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | If set, use Anthropic provider instead. Requires `ANTHROPIC_API_KEY`. |
| `ANTHROPIC_API_KEY` | API key for Anthropic provider |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP endpoint for trace export |
| `DISABLE_TELEMETRY` | Set `true` to disable all tracing |
| `WEBHOOK_HOST` / `WEBHOOK_PORT` | Webhook server bind address |
| `GITLAB_WEBHOOK_LABEL` | Label that triggers review (default `ai-review-requested`) |
| `GITLAB_WEBHOOK_REVIEW_ALL` | Bypass label requirement (`true`/`false`) |
| `GITLAB_WEBHOOK_TOKEN` | Secret token for webhook validation |
| `CONFIDENCE_THRESHOLD` | Min confidence for inline comments (default `0.9`) |
| `AGENT_REQUEST_LIMIT` | Max API requests per agent run (default `200`) |
| `MAX_LINES` / `MAX_LINE_LENGTH` | Diff truncation limits (default `200` / `150`) |
| `MAX_PARALLEL_REVIEWS` | Max concurrent reviews for webhook server (default `3`, `0`=unlimited) |

## Testing

Tests in `tests/` cover `utils`, `graph`, and end-to-end tool execution. CI runs via `.gitlab-ci.yml` with Podman available. `test_tools_e2e.py` requires Podman running.

**After every change**, run the full suite from the venv:

```bash
.venv/bin/python -m unittest discover -s tests && .venv/bin/mypy review_bot/
```

## Key Design Decisions

**Keep this section up to date when adding or changing architectural choices.**

- **Sequential sub-agent execution** (not parallel) — all agents share the same system prompt, maximizing LLM prefix cache hits. Only the specialty suffix differs per agent.
- **Critic as gatekeeper** — sub-agents are permissive; the critic filters false positives (confidence < 0.7), enforces thresholds, and strips all positive feedback.
- **Podman sandbox** — agents execute commands in an isolated container. `ContainerManager` is the single delegation point for all sandbox access.
- **Ephemeral RAG** — ChromaDB index is built in-memory per review; no persistent storage.
- **Async-first** — the entire pipeline (`orchestration/pipeline.py`), CLI (`cli.py`), and tool functions are `async def`.
- **Diff coordinate resolution** (`utils/diff.py:resolve_diff_coordinates`) — maps new-file line numbers back to old-file coordinates for accurate GitLab inline comments, handling renames.
- **Top-level entrypoints only** — `review_bot/` contains only `__init__.py`, `cli.py`, `gitlab_webhook.py`, and `config.py`. Every implementation detail lives in a sub-package. This follows Clean Code: the top-level is a table of contents; the sub-packages are the chapters.
- **Minimal change preference** — when implementing features, prefer the smallest possible change. When you can achieve the same outcome by removing or simplifying existing code instead of adding new code, do that.
