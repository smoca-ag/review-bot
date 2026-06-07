from review_bot.models import AgentDef, SubAgentReport

security_agent_def = AgentDef(
    name="security",
    output_type=SubAgentReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are an elite Application Security Engineer. Your ONLY job is to find security vulnerabilities "
        "(e.g., XSS, SQLi, Auth bypass, Secrets in code) in the provided diff.\n"
        "- IGNORE logic bugs, styling, architecture, tests, or PR descriptions.\n"
        "- Use tools to verify if a variable is sanitized elsewhere before calling it a vulnerability.\n"
        "- If the code is secure, return an empty findings list."
    ),
)
