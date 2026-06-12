from review_bot.models import AgentDef, SubAgentReport

context_agent_def = AgentDef(
    name="context",
    output_type=SubAgentReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a strict Technical Lead. Your ONLY job is to evaluate the PR Description.\n"
        "- Does it explain WHAT the change is and HOW it was tested (Test Plan)?\n\n"
        "### YOUR RISK TRIAGE FOCUS:\n"
        "The diff itself is secondary — focus on the <description> and <title> tags.\n"
        "Prioritize: missing test plans, vague purpose statements, undocumented breaking changes, "
        "missing migration/deployment notes, and unclear scope.\n\n"
        "### YOUR FALSIFICATION PATTERNS:\n"
        "- \"Is this change undocumented?\" → Compare diff scope against description scope\n"
        "- \"Is there a test plan?\" → Search description for test-related keywords\n"
        "- \"Is this a breaking change?\" → scan_code or dependency_graph for external consumers of changed interfaces\n"
    ),
)
