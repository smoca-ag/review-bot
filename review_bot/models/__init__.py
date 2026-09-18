from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


@dataclass
class ReviewDeps:
    mr_request: Any
    container_manager: Any
    mr_description: str
    vector_index: Any
    dependency_graph: Any = None
    todo_items: list[dict] = field(default_factory=list)
    agent_name: str = ""


class LineComment(BaseModel):
    file: str = Field(description="The file path where the issue was found.")
    line: int = Field(description="The starting line number of the issue.")
    end_line: int | None = Field(
        default=None,
        description="The ending line number for multi-line findings. None if single line.",
    )
    risk_score: int = Field(
        ge=1,
        le=5,
        description="Risk score from Phase 1 triage (1=negligible, 5=critical).",
    )
    category: str = Field(description="e.g., security, logic, performance, test.")
    hypothesis: str = Field(
        description="The falsifiable claim: 'In <file>:<line>, <claim> because <evidence>'."
    )
    falsification_method: str = Field(
        description="How this hypothesis was tested: tool call and query used to attempt to disprove it."
    )
    verification: Literal["confirmed", "inconclusive"] = Field(
        description="'confirmed' if falsification failed (hypothesis stands), 'inconclusive' if test was unclear."
    )
    counter_argument: str = Field(
        description="Devil's advocate: Why might this code actually be correct?"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Certainty score from 0.0 to 1.0."
    )
    comment: str = Field(description="The human-readable comment text for the review.")


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
    summary: str = Field(
        description=(
            "A brief summary of the combined findings. One or two sentences, max ~40 words."
        )
    )
    has_purpose: bool
    has_test_plan: bool
    description_feedback: list[str] = Field(
        description=(
            "Only missing/vague/inadequate description elements. "
            "One sentence per item, max 3 items. [] if fine."
        )
    )
    security_concerns: list[str] = Field(
        description=(
            "High-level security warnings to put in the PR body. "
            "One sentence per item, max 3 items."
        )
    )
    architectural_feedback: list[str] = Field(
        description=(
            "High-level design and structure feedback. One sentence per item, max 3 items."
        )
    )
    testing_feedback: list[str] = Field(
        description=(
            "High-level testing strategy and coverage feedback. "
            "One sentence per item, max 3 items."
        )
    )
    performance_feedback: list[str] = Field(
        description=(
            "High-level performance and scalability feedback. "
            "One sentence per item, max 3 items."
        )
    )
    actionable_feedback: list[str] = Field(
        description=(
            "High-level code bugs to put in the PR body. One sentence per item, max 3 items."
        )
    )
    recommend_approval: bool = Field(
        description="True if there are no major issues and description is adequate."
    )
    critical_line_comments: list[LineComment] = Field(
        description="Filtered list of ONLY high-confidence line comments."
    )


class BotImprovementSuggestion(BaseModel):
    timestamp: str = Field(
        description="ISO 8601 timestamp when the suggestion was made."
    )
    agent_name: str = Field(
        description="Name of the agent that made the suggestion (e.g., 'security', 'logic')."
    )
    category: Literal[
        "missing_tool",
        "missing_dependency",
        "missing_capability",
        "prompt_improvement",
        "other",
    ] = Field(description="Category of the improvement suggestion.")
    description: str = Field(
        description="What limitation was encountered during the review."
    )
    suggestion: str = Field(
        description="Concrete suggestion to improve the bot (e.g., 'Install mypy in the container')."
    )
    context: str = Field(
        description="Context where the limitation was encountered (e.g., file path, code snippet, or scenario)."
    )


@dataclass
class AgentDef:
    name: str
    output_type: type[BaseModel]
    specialty_prompt: str