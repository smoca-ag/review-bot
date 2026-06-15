"""Dependency graph — cross-language import/export analysis via tree-sitter.

Delegates to ``review_bot.graph`` for the implementation details.
"""

from review_bot.graph import (
    DependencyGraph,
    ImportRef,
    LanguageConfig,
    ModuleInfo,
    build_dependency_graph,
)

__all__ = [
    "build_dependency_graph",
    "DependencyGraph",
    "ImportRef",
    "LanguageConfig",
    "ModuleInfo",
]