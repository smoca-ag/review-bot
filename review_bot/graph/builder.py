"""Graph builder — walks the repo and constructs the DependencyGraph."""

import logging
import os

from review_bot.config import EXCLUDE_DIRS, EXCLUDE_DOT_DIRS, SOURCE_EXTENSIONS
from review_bot.graph.extractors import (
    _build_language_configs,
    _parse,
    _ts_language,
)
from review_bot.graph.model import DependencyGraph, LanguageConfig, ModuleInfo

logger = logging.getLogger(__name__)

_MAX_FILE_LINES = 5000

EXT_TO_LANG: dict[str, str] = {}
_LANGUAGE_CONFIGS: dict[str, LanguageConfig] | None = None


def _get_language_configs():
    global _LANGUAGE_CONFIGS, EXT_TO_LANG
    if _LANGUAGE_CONFIGS is None:
        try:
            _LANGUAGE_CONFIGS = _build_language_configs()
        except ImportError:
            logger.warning("tree-sitter language packages not fully installed")
            _LANGUAGE_CONFIGS = {}
        EXT_TO_LANG = {}
        for lang_name, cfg in _LANGUAGE_CONFIGS.items():
            for ext in cfg.extensions:
                EXT_TO_LANG[ext] = lang_name
    return _LANGUAGE_CONFIGS


def _detect_language(file_path: str) -> str | None:
    _get_language_configs()
    ext = os.path.splitext(file_path)[1].lower()
    return EXT_TO_LANG.get(ext)


def build_dependency_graph(repo_dir: str) -> DependencyGraph:
    lang_configs = _get_language_configs()
    graph = DependencyGraph()

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDE_DIRS
            and not (EXCLUDE_DOT_DIRS and d.startswith("."))
        ]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue
            file_path = os.path.join(root, f)
            rel_path = os.path.relpath(file_path, repo_dir)
            lang_name = _detect_language(rel_path)
            if lang_name is None:
                continue

            cfg = lang_configs.get(lang_name)
            if cfg is None:
                continue

            try:
                with open(file_path, "rb") as fh:
                    source = fh.read()
            except (IOError, OSError):
                continue

            if source.count(b"\n") > _MAX_FILE_LINES:
                continue

            lang = _ts_language(cfg)
            try:
                imports = cfg.extract_imports(source, lang)
                definitions = cfg.extract_definitions(source, lang)
            except Exception:
                logger.debug("tree-sitter parse error for %s", rel_path)
                continue

            for imp in imports:
                imp.resolved = cfg.resolve_import(imp.raw, rel_path, repo_dir)

            info = ModuleInfo(
                file_path=rel_path,
                language=lang_name,
                imports=imports,
                definitions=definitions,
            )
            graph.add_module(info)

    return graph