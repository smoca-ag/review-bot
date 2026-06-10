from review_bot.models import AgentDef, SubAgentReport

context_agent_def = AgentDef(
    name="context",
    output_type=SubAgentReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a strict Technical Lead. Your ONLY job is to evaluate the PR Description.\n"
        "- Does it explain WHAT the change is and HOW it was tested (Test Plan)?\n"
    ),
)
