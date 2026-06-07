from review_bot.models import AgentDef, SubAgentReport

performance_agent_def = AgentDef(
    name="performance",
    output_type=SubAgentReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a Performance & Scalability Engineer. Your ONLY job is to identify system-crashing scale issues.\n"
        "- Hunt for N+1 database queries, missing indexes, memory leaks, and inefficient Big-O complexity.\n"
        "- Think about what happens when this code processes 10 million records, not 10 records."
    ),
)
