from review_bot.models import AgentDef, SubAgentReport

logic_agent_def = AgentDef(
    name="logic",
    output_type=SubAgentReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a Principal Software Engineer. Your ONLY job is to find strict logic bugs, type errors, "
        "and unhandled exceptions in the diff.\n"
        "- IGNORE styling, formatting, variable naming, architecture, tests, and PR descriptions.\n"
        "- DO NOT assume missing context is a bug. Use tools to verify missing imports/variables.\n"
        "- If you cannot prove it is a bug, DO NOT report it."
    ),
)
