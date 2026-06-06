from pydantic import BaseModel, Field
from review_bot.models import LineComment, AgentDef

class SecurityReport(BaseModel):
    findings: list[LineComment] = Field(
        description="Security vulnerabilities found. Empty if none."
    )
    summary: str = Field(description="Summary of security posture.")

security_agent_def = AgentDef(
    name="security",
    output_type=SecurityReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are an elite Application Security Engineer. Your ONLY job is to find security vulnerabilities "
        "(e.g., XSS, SQLi, Auth bypass, Secrets in code) in the provided diff.\n"
        "- IGNORE logic bugs, styling, architecture, tests, or PR descriptions.\n"
        "- Use tools to verify if a variable is sanitized elsewhere before calling it a vulnerability.\n"
        "- If the code is secure, return an empty findings list."
    )
)
