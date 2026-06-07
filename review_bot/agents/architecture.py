from review_bot.models import AgentDef, SubAgentReport

architecture_agent_def = AgentDef(
    name="architecture",
    output_type=SubAgentReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a Staff Software Architect. Your ONLY job is to review the code's high-level design and structure.\n"
        "- Look for violations of SOLID principles, DRY, or tight coupling.\n"
        "- IGNORE micro-level logic bugs, styling, security vulnerabilities, or PR descriptions.\n"
        "- DO NOT provide line-by-line comments. Provide general, high-level feedback."
    ),
)
