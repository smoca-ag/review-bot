from .security import security_agent_def, SecurityReport
from .logic import logic_agent_def, LogicReport
from .architecture import architecture_agent_def, ArchitectureReport
from .context import context_agent_def, ContextReport
from .test import test_agent_def, TestReport
from .performance import performance_agent_def, PerformanceReport
from .critic import critic_agent_def

SUB_AGENTS = [
    security_agent_def,
    logic_agent_def,
    architecture_agent_def,
    context_agent_def,
    test_agent_def,
    performance_agent_def,
]

__all__ = [
    "SUB_AGENTS",
    "critic_agent_def",
    "SecurityReport",
    "LogicReport",
    "ArchitectureReport",
    "ContextReport",
    "TestReport",
    "PerformanceReport",
]
