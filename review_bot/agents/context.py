from pydantic import BaseModel, Field

from review_bot.models import AgentDef


class ContextReport(BaseModel):
    has_purpose: bool = Field(description="True if MR explains the 'what'.")
    has_test_plan: bool = Field(description="True if MR explains the 'how' or testing.")
    high_level_feedback: list[str] = Field(
        default_factory=list,
        description="Actionable feedback strictly regarding missing PR context.",
    )
    summary: str = Field(
        default="", description="Summary of the PR description quality."
    )


context_agent_def = AgentDef(
    name="context",
    output_type=ContextReport,
    specialty_prompt=(
        "\n\n### YOUR ASSIGNED SPECIALTY ROLE:\n"
        "You are a strict Technical Lead. Your ONLY job is to evaluate the PR Description.\n"
        "- Does it explain WHAT the change is and HOW it was tested (Test Plan)?\n"
    ),
)
