"""Agent pipeline — runs sub-agents sequentially, then the critic gatekeeper."""

import logging
from dataclasses import replace
from datetime import date

from opentelemetry import trace

from review_bot.agents import SUB_AGENTS, critic_agent_def
from review_bot.config import AGENT_REQUEST_LIMIT
from review_bot.models import FinalReviewResult, ReviewDeps
from review_bot.utils.diff import truncate_large_diff_files
from review_bot.utils.text import inject_line_numbers, wrap_in_cdata

logger = logging.getLogger(__name__)


async def run_agent_with_span(agent_name, agent, prompt, deps, usage_limits, message_history=None):
    """Run one agent inside an OTel span.

    Args:
        agent_name: Name used for the span and telemetry attributes.
        agent: The pydantic-ai Agent instance to run.
        prompt: The user prompt for this run.
        deps: ReviewDeps passed to the agent and its tools.
        usage_limits: pydantic-ai UsageLimits for this run.
        message_history: Prior conversation messages to continue, or None to
            start fresh.

    Returns:
        The AgentRunResult of the run.
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(f"agent_{agent_name}") as _span:
        return await agent.run(
            prompt, deps=deps, usage_limits=usage_limits, message_history=message_history
        )


def build_review_prompt(mr_request) -> str:
    """Assemble the base review prompt from MR metadata and diff."""
    diff_content = mr_request.diff() or ""

    if diff_content:
        original_diff = diff_content
        diff_content = truncate_large_diff_files(diff_content)
        if diff_content != original_diff:
            logger.info("Applied diff truncation for large files.")

    mr_description = mr_request.description() or "No description provided."
    title = mr_request.title() or "No title provided."

    return (
        f"Review the following Merge Request details:\n\n"
        f"### MR TITLE:\n<title>\n{wrap_in_cdata(title)}\n</title>\n\n"
        f"### MR DESCRIPTION:\n<description>\n{wrap_in_cdata(mr_description)}\n</description>\n\n"
        f"### CODE DIFF:\n<untrusted_diff>\n{wrap_in_cdata(inject_line_numbers(diff_content))}\n</untrusted_diff>\n\n"
        f"### CURRENT DATE:\n{date.today().isoformat()}"
    )


async def run_agent_pipeline(
    agents,
    secure_base_prompt,
    mr_request,
    container_manager,
    vector_index,
    dep_graph=None,
):
    """Execute sub-agents sequentially, then run the critic.

    The context agent runs on the full prompt and its transcript is reused as
    message_history for the five judgment agents, so the MR content and the
    fact-finding exploration are sent to the model only once. Judgment agents
    still reach their own conclusions independently — only fact-finding is
    shared. The critic runs fresh on the consolidated reports.

    Returns the FinalReviewResult from the critic.
    """
    from pydantic_ai.usage import UsageLimits

    usage_limits = UsageLimits(request_limit=AGENT_REQUEST_LIMIT)
    mr_description = mr_request.description() or "No description provided."

    deps = ReviewDeps(
        mr_request=mr_request,
        container_manager=container_manager,
        mr_description=mr_description,
        vector_index=vector_index,
        dependency_graph=dep_graph,
    )

    logger.info(
        f"Launching {len(SUB_AGENTS)} specialized agents sequentially (context transcript seeded to judgment agents)..."
    )

    reports = {}
    context_transcript = None
    for agent_def in SUB_AGENTS:
        agent_deps = replace(deps, todo_items=[], agent_name=agent_def.name)
        if context_transcript is None:
            res = await run_agent_with_span(
                agent_def.name,
                agents[f"{agent_def.name}_agent"],
                secure_base_prompt + agent_def.specialty_prompt,
                deps=agent_deps,
                usage_limits=usage_limits,
            )
            if agent_def.name == "context":
                context_transcript = res.all_messages()
        else:
            res = await run_agent_with_span(
                agent_def.name,
                agents[f"{agent_def.name}_agent"],
                agent_def.specialty_prompt,
                deps=agent_deps,
                usage_limits=usage_limits,
                message_history=context_transcript,
            )
        reports[agent_def.name] = res.output

    logger.info(
        "Sub-agents finished. Passing to Critic Agent for consolidation & filtering..."
    )

    critic_prompt = secure_base_prompt + critic_agent_def.specialty_prompt
    for name, report in reports.items():
        safe_report = wrap_in_cdata(report.model_dump_json())
        critic_prompt += f"### {name.upper()} REPORT:\n<{name}_report>\n{safe_report}\n</{name}_report>\n\n"

    critic_deps = replace(deps, todo_items=[], agent_name=critic_agent_def.name)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("agent_critic"):
        final_result = await agents["critic_agent"].run(critic_prompt, deps=critic_deps, usage_limits=usage_limits)

    review_result: FinalReviewResult = final_result.output
    span = trace.get_current_span()
    for name, report in reports.items():
        if hasattr(report, "findings"):
            span.set_attribute(f"review.{name}_findings", len(report.findings))
    span.set_attribute(
        "review.final_critical_comments",
        len(review_result.critical_line_comments),
    )

    return review_result