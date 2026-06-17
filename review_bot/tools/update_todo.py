from review_bot.models import ReviewDeps
from pydantic_ai import RunContext


def update_todo(
    ctx: RunContext[ReviewDeps],
    action: str,
    issue_id: str,
    state: str | None = None,
    description: str | None = None,
) -> str:
    """
    Track issues through the 4-phase review workflow.

    Use this to keep an explicit checklist of every issue you discover,
    so you don't lose or double-count findings during a long review.

    Args:
        action: "add" to log a new issue, "update" to change state/description,
                "drop" to discard (false positive), "list" to see all tracked issues.
        issue_id: Short unique identifier for this issue (e.g. "auth-sqli-1", "perf-n1-query").
        state: Current pipeline state. One of:
               triaged — risk scored, queued
               hypothesis — claim formed
               falsified — disproven by tool, ready to discard
               confirmed — survived falsification
               dropped — removed (false positive, low confidence, etc.)
        description: What was found, what changed, or what tool result was.
    """
    todo = ctx.deps.todo_items

    if action == "list":
        if not todo:
            return "No issues tracked yet."
        lines = []
        for i, item in enumerate(todo, 1):
            lines.append(f"  [{item.get('state', '?')}] {item['issue_id']}: {item.get('description', '')}")
        return "Tracked issues:\n" + "\n".join(lines)

    if action == "drop":
        for item in todo:
            if item["issue_id"] == issue_id:
                item["state"] = "dropped"
                return f"[TODO] {issue_id} → dropped"
        return f"[TODO] Issue '{issue_id}' not found."

    if action == "add":
        if any(item["issue_id"] == issue_id for item in todo):
            return f"[TODO] Issue '{issue_id}' already exists. Use action='update' to modify."
        todo.append(dict(issue_id=issue_id, state=state or "triaged", description=description or ""))
        return f"[TODO] Added {issue_id} [{state or 'triaged'}]"

    if action == "update":
        for item in todo:
            if item["issue_id"] == issue_id:
                if state:
                    item["state"] = state
                if description:
                    item["description"] = description
                return f"[TODO] {issue_id} → [{item['state']}] {item['description']}"
        return f"[TODO] Issue '{issue_id}' not found. Use action='add' first."

    return f"[TODO] Unknown action: '{action}'. Use add, update, drop, or list."