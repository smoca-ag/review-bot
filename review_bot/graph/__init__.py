"""Dependency graph package — cross-language import/export analysis via tree-sitter."""

from review_bot.graph.model import DependencyGraph, ImportRef, LanguageConfig, ModuleInfo
from review_bot.graph.builder import build_dependency_graph, _detect_language, _get_language_configs

__all__ = [
    "build_dependency_graph",
    "DependencyGraph",
    "ImportRef",
    "LanguageConfig",
    "ModuleInfo",
]