from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from review_bot.backend.base_backend import Shell


@dataclass
class ReviewDeps:
    mr_request: Any
    mr_description: str
    vector_index: Any
    shell: Optional[Shell] = None


class LineComment(BaseModel):
    file: str = Field(description="The file path where the issue was found.")
    line: int = Field(description="The line number of the issue.")
    severity: Literal["critical", "major", "minor"] = Field(
        description="Severity of the issue."
    )
    category: str = Field(description="e.g., security, logic, performance, test.")
    false_positive_reasoning: str = Field(
        description="Play devil's advocate: Why might this code actually be correct?"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Certainty score from 0.0 to 1.0."
    )
    comment: str = Field(description="The comment text.")


class SubAgentReport(BaseModel):
    findings: list[LineComment] = Field(
        default_factory=list,
        description="Specific line-by-line issues found. Empty if none.",
    )
    high_level_feedback: list[str] = Field(
        default_factory=list,
        description="High-level feedback, architectural issues, or general concerns not tied to a specific line.",
    )
    summary: str = Field(
        default="",
        description="Summary of the agent's findings based on its specialty.",
    )


class FinalReviewResult(BaseModel):
    summary: str = Field(description="A brief summary of the combined findings.")
    has_purpose: bool
    has_test_plan: bool
    description_feedback: list[str]
    security_concerns: list[str] = Field(
        description="High-level security warnings to put in the PR body."
    )
    architectural_feedback: list[str] = Field(
        description="High-level design and structure feedback."
    )
    testing_feedback: list[str] = Field(
        description="High-level testing strategy and coverage feedback."
    )
    performance_feedback: list[str] = Field(
        description="High-level performance and scalability feedback."
    )
    actionable_feedback: list[str] = Field(
        description="High-level code bugs to put in the PR body."
    )
    recommend_approval: bool = Field(
        description="True if there are no major issues and description is adequate."
    )
    critical_line_comments: list[LineComment] = Field(
        description="Filtered list of ONLY high-confidence line comments."
    )


@dataclass
class AgentDef:
    name: str
    output_type: type[BaseModel]
    specialty_prompt: str
