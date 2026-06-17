---
name: plan-review-bot-change
description: Use before implementing ANY feature, fix, or refactor in review-bot. Maps requirements → affected modules → ordered change plan → verification → convention checks. Outputs a plan for user confirmation; makes zero code changes unless user says "implement the plan."
always-loaded: false
---

# Plan a review-bot change

## When to use this skill

Activate whenever the user asks to add, change, or fix something in review-bot **before** writing any code. This skill produces a structured plan for user confirmation. It never edits files — the user must explicitly say "implement the plan" or "go ahead" before any code is written.

Skip this skill when:
- The user explicitly asks to bypass planning ("just do it", "quick fix")
- The change is trivial (one-line typo fix, updating a docstring, adding a single import)
- The user is asking a question, not requesting a change

## Phases

Work through these in order. After each phase, output the result compactly as markdown. Do not proceed to the next phase until the current one produces useful output.

### 1. Requirement extraction

Parse the user request into concrete outcomes:
- What should happen differently after the change?
- What inputs/outputs change?
- What invariants must hold? (what must NOT break)
- Are there edge cases or error states to consider?

If the request is ambiguous, ask exactly one clarifying question. Don't guess.

### 2. Goal / use-case

A 1–2 sentence narrative: **who** triggers this, **under what conditions**, and **what outcome do they see?** Keep it concrete. If you can't state the goal in 2 sentences, the request is too vague — go back to phase 1 and narrow scope.

### 3. Code-path mapping

Read the directory map in `AGENTS.md`, then read the relevant source files to identify:

- **Primary modules** that must change (orchestration, models, tools, backend, agents, graph, rag, utils)
- **Secondary modules** indirectly affected (callers, type consumers, CLI argument surface, webhook path)
- **Configuration impact** — does this need a new env var, a new CLI flag, or a change to existing config? If yes, flag that `AGENTS.md` Configuration table, `README.md`, and `.env` example must all be updated.

Use the exploration tools (glob, grep, read) to verify the affected code paths exist and understand current behavior before planning changes.

### 4. Ordered change plan

Produce a numbered list of atomic edits, each with:

| Field | Description |
|---|---|
| **File** | Absolute path |
| **Action** | add / modify / remove |
| **What** | Concise description of the change |
| **Why** | Traceable to a phase-1 requirement |
| **Depends on** | Which earlier step(s) must land first, or "none" |

Order steps so dependencies precede dependents. Group related changes to the same file into a single step when no other step depends on an intermediate state.

### 5. Verification

Concrete pass/fail criteria, split into two tiers:

- **Automated:** The exact test command(s) to run. Prefer `-k <pattern>` to run only relevant tests. If no test exists for this behavior, say so and suggest what new test to write.
  ```
  .venv/bin/python -m unittest discover -s tests -k test_foo
  ```
- **Manual:** A step-by-step scenario to exercise the change end-to-end. Include the exact CLI command or webhook trigger, the expected stdout/stderr output, and how to confirm the side effect (e.g., check GitLab inline comment, check log line).

### 6. Convention checks

Verify the plan against `AGENTS.md` conventions with a checklist. Each item gets `[x]` or `[ ]` with a one-word note if failing.

| Check | Rule |
|---|---|
| Union syntax | Uses `str \| None`, not `Optional[str]` |
| Async-first | New functions are `async def` where pipeline/tools run |
| Google docstrings | Args/Returns/Raises style docstrings on public functions |
| Minimal change | Prefers remove/simplify over add; no dead code |
| No new env var | Or if yes, flags AGENTS.md/README.md/.env updates |
| Test suite | Verifies `unittest discover` + `mypy review_bot/` pass |
| Top-level entrypoint | `review_bot/` stays table of contents; impl in sub-packages |

## Output format

Present the full plan as a single markdown block after phase 6:

```
## Plan: <short name>

### Goal
<1–2 sentence use-case>

### Affected modules
- `path/to/module.py` — what changes here
- ...

### Ordered changes
1. `path/to/file.py` — [modify] change X because Y (dep: none)
2. ...

### Verification
- Automated: `unittest -k ...`
- Manual: step-by-step ...

### Convention checks
- [x] union syntax
- [x] async def
- [ ] ...
```

## Guardrail

**Do not write code during this skill's execution.** No edits, no file writes, no `bash` commands that create or modify files. Read-only operations only (read, glob, grep). The plan must be confirmed by the user before any implementation begins.
