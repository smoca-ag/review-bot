"""Core data structures for the dependency graph."""

from dataclasses import dataclass, field
from typing import Any, Callable

import tree_sitter as ts


@dataclass
class ImportRef:
    raw: str
    resolved: str | None = None


@dataclass
class ModuleInfo:
    file_path: str
    language: str
    imports: list[ImportRef] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)


@dataclass
class DependencyGraph:
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    dependents: dict[str, set[str]] = field(default_factory=dict)

    def add_module(self, info: ModuleInfo) -> None:
        self.modules[info.file_path] = info
        for imp in info.imports:
            if imp.resolved:
                self.dependents.setdefault(imp.resolved, set()).add(info.file_path)


@dataclass
class LanguageConfig:
    extensions: set[str]
    language_fn: Callable[[], Any]
    extract_imports: Callable[[bytes, ts.Language], list[ImportRef]]
    extract_definitions: Callable[[bytes, ts.Language], list[str]]
    resolve_import: Callable[[str, str, str], str | None]
