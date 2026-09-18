"""Agent factory — creates fresh pydantic-ai Agent instances for a review run."""

from review_bot.agents import SUB_AGENTS, critic_agent_def
from review_bot.agents.prompt import SHARED_SUB_AGENT_SYSTEM_PROMPT
from review_bot.config import ensure_setup, resolve_model
from review_bot.models import ReviewDeps
from review_bot.tools import shared_tools

from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking


def create_agents() -> dict:
    """Create and return fresh agent instances for this review run."""
    ensure_setup()
    model = resolve_model()

    agent_config = {
        "model": model,
        "deps_type": ReviewDeps,
        "tools": shared_tools,
        "retries": 3,
        "capabilities": [Thinking(effort="medium")],
        "model_settings": {"timeout": 1800},
        "system_prompt": SHARED_SUB_AGENT_SYSTEM_PROMPT,
    }

    agents = {}
    for agent_def in SUB_AGENTS:
        agents[f"{agent_def.name}_agent"] = Agent(  # type: ignore[call-overload]
            output_type=agent_def.output_type, name=agent_def.name, **agent_config
        )

    critic_config = agent_config.copy()
    agents["critic_agent"] = Agent(  # type: ignore[call-overload]
        output_type=critic_agent_def.output_type,
        name=critic_agent_def.name,
        **critic_config,
    )
    return agents