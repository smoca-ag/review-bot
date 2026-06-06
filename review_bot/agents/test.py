from pydantic import BaseModel, Field
from review_bot.models import LineComment, AgentDef

class TestReport(BaseModel):
    findings: list[LineComment] = Field(
        description="Specific, critical flaws in test logic. Empty if none."
    )
    testing_feedback: list[str] = Field(
        description="High-level feedback on missing test cases."
    )
    summary: str = Field(description="Summary of test quality.")

test_agent_def = AgentDef(
    name="test",
    output_type=TestReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a QA and Test Automation Engineer. Your ONLY job is to evaluate test coverage and edge cases.\n"
        "- Identify edge cases, boundary conditions, and race conditions that the current code/tests miss.\n"
        "- Review existing tests in the diff to ensure they actually assert meaningful outcomes (no 'happy path only' tests).\n"
        "- If the project has no tests at all, return an empty findings list.\n"
        "- IGNORE general logic bugs outside of testing, architecture, styling, and security."
    )
)
