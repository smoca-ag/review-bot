"""Per-language tree-sitter extractors and import resolvers."""

import os

import tree_sitter as ts

from review_bot.graph.model import ImportRef, LanguageConfig

_ts_parse = None


def _parse(source: bytes, lang: ts.Language) -> ts.Tree:
    global _ts_parse
    if _ts_parse is None:
        _ts_parse = ts.Parser
    return _ts_parse(lang).parse(source)


def _ts_language(cfg: LanguageConfig) -> ts.Language:
    return ts.Language(cfg.language_fn())


# --- TypeScript / TSX ---


def _extract_ts_imports(source: bytes, lang: ts.Language) -> list[ImportRef]:
    tree = _parse(source, lang)
    imports: list[ImportRef] = []
    for child in tree.root_node.children:
        if child.type == "import_statement":
            for sub in child.children:
                if sub.type == "string":
                    frag = None
                    for fc in sub.children:
                        if fc.type == "string_fragment":
                            frag = source[fc.start_byte:fc.end_byte].decode()
                            break
                    if frag:
                        imports.append(ImportRef(raw=frag))
    return imports


def _extract_ts_definitions(source: bytes, lang: ts.Language) -> list[str]:
    tree = _parse(source, lang)
    defs: list[str] = []
    for child in tree.root_node.children:
        if child.type in ("export_statement",):
            for sub in child.children:
                if sub.type == "function_declaration":
                    for sc in sub.children:
                        if sc.type == "identifier":
                            defs.append(source[sc.start_byte:sc.end_byte].decode())
                elif sub.type == "class_declaration":
                    for sc in sub.children:
                        if sc.type == "type_identifier":
                            defs.append(source[sc.start_byte:sc.end_byte].decode())
        elif child.type in ("function_declaration",):
            for sc in child.children:
                if sc.type == "identifier":
                    defs.append(source[sc.start_byte:sc.end_byte].decode())
        elif child.type in ("class_declaration",):
            for sc in child.children:
                if sc.type == "type_identifier":
                    defs.append(source[sc.start_byte:sc.end_byte].decode())
    return defs


def _resolve_ts_import(raw: str, source_file: str, repo_dir: str) -> str | None:
    if raw.startswith("."):
        base = os.path.dirname(source_file)
        candidates = [
            os.path.join(repo_dir, base, raw),
            os.path.join(repo_dir, base, raw + ".ts"),
            os.path.join(repo_dir, base, raw + ".tsx"),
            os.path.join(repo_dir, base, raw + ".js"),
            os.path.join(repo_dir, base, raw, "index.ts"),
            os.path.join(repo_dir, base, raw, "index.tsx"),
            os.path.join(repo_dir, base, raw, "index.js"),
        ]
        for c in candidates:
            full = os.path.normpath(c)
            if os.path.isfile(full):
                return os.path.relpath(full, repo_dir)
    return None


# --- Ruby ---


def _extract_ruby_imports(source: bytes, lang: ts.Language) -> list[ImportRef]:
    tree = _parse(source, lang)
    imports: list[ImportRef] = []
    for child in tree.root_node.children:
        if child.type == "call":
            method_name = None
            for sub in child.children:
                if sub.type == "identifier":
                    method_name = source[sub.start_byte:sub.end_byte].decode()
                    break
            if method_name not in ("require", "require_relative"):
                continue
            for sub in child.children:
                if sub.type == "argument_list":
                    for arg in sub.children:
                        if arg.type == "string":
                            for fc in arg.children:
                                if fc.type == "string_content":
                                    imports.append(
                                        ImportRef(
                                            raw=source[fc.start_byte:fc.end_byte].decode(),
                                        )
                                    )
    return imports


def _extract_ruby_definitions(source: bytes, lang: ts.Language) -> list[str]:
    tree = _parse(source, lang)
    defs: list[str] = []

    def _walk(node: ts.Node, depth: int = 0) -> None:
        if depth > 6:
            return
        if node.type == "class":
            for sub in node.children:
                if sub.type == "constant":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
                    break
        elif node.type == "method":
            for sub in node.children:
                if sub.type == "identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
                    break
        elif node.type == "module":
            for sub in node.children:
                if sub.type == "constant":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
                    break
        for child in node.children:
            _walk(child, depth + 1)

    _walk(tree.root_node)
    return defs


def _resolve_ruby_import(raw: str, source_file: str, repo_dir: str) -> str | None:
    base = os.path.dirname(source_file)
    candidates = [
        os.path.join(repo_dir, base, raw + ".rb"),
        os.path.join(repo_dir, base, raw, os.path.basename(raw) + ".rb"),
        os.path.join(repo_dir, raw + ".rb"),
        os.path.join(repo_dir, raw, os.path.basename(raw) + ".rb"),
    ]
    for c in candidates:
        full = os.path.normpath(c)
        if os.path.isfile(full):
            return os.path.relpath(full, repo_dir)
    return None


# --- Swift ---


def _extract_swift_imports(source: bytes, lang: ts.Language) -> list[ImportRef]:
    tree = _parse(source, lang)
    imports: list[ImportRef] = []
    for child in tree.root_node.children:
        if child.type == "import_declaration":
            for sub in child.children:
                if sub.type == "identifier":
                    for sc in sub.children:
                        if sc.type == "simple_identifier":
                            imports.append(
                                ImportRef(
                                    raw=source[sc.start_byte:sc.end_byte].decode(),
                                )
                            )
    return imports


def _extract_swift_definitions(source: bytes, lang: ts.Language) -> list[str]:
    tree = _parse(source, lang)
    defs: list[str] = []

    def _walk(node: ts.Node, depth: int = 0) -> None:
        if depth > 6:
            return
        if node.type == "class_declaration":
            for sub in node.children:
                if sub.type == "type_identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif node.type == "struct_declaration":
            for sub in node.children:
                if sub.type == "type_identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif node.type == "enum_declaration":
            for sub in node.children:
                if sub.type == "type_identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif node.type == "protocol_declaration":
            for sub in node.children:
                if sub.type == "type_identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif node.type == "function_declaration":
            for sub in node.children:
                if sub.type == "simple_identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif node.type == "protocol_function_declaration":
            for sub in node.children:
                if sub.type == "simple_identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        for child in node.children:
            _walk(child, depth + 1)

    _walk(tree.root_node)
    return defs


def _resolve_swift_import(raw: str, source_file: str, repo_dir: str) -> str | None:
    spm_dirs = ["Sources", "Source", "src"]
    for spm_dir in spm_dirs:
        target_dir = os.path.join(repo_dir, spm_dir, raw)
        if os.path.isdir(target_dir):
            for ext in (".swift",):
                for root, _, files in os.walk(target_dir):
                    for f in files:
                        if f.endswith(ext):
                            full = os.path.join(root, f)
                            return os.path.relpath(full, repo_dir)
        candidate = os.path.join(repo_dir, spm_dir, raw + ".swift")
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, repo_dir)
    candidate = os.path.join(repo_dir, raw + ".swift")
    if os.path.isfile(candidate):
        return os.path.relpath(candidate, repo_dir)
    return None


# --- Kotlin ---


def _extract_kotlin_imports(source: bytes, lang: ts.Language) -> list[ImportRef]:
    tree = _parse(source, lang)
    imports: list[ImportRef] = []
    for child in tree.root_node.children:
        if child.type == "import":
            for sub in child.children:
                if sub.type == "qualified_identifier":
                    imports.append(
                        ImportRef(
                            raw=source[sub.start_byte:sub.end_byte].decode(),
                        )
                    )
    return imports


def _extract_kotlin_definitions(source: bytes, lang: ts.Language) -> list[str]:
    tree = _parse(source, lang)
    defs: list[str] = []
    for child in tree.root_node.children:
        if child.type == "class_declaration":
            for sub in child.children:
                if sub.type == "identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif child.type == "function_declaration":
            for sub in child.children:
                if sub.type == "identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
        elif child.type == "object_declaration":
            for sub in child.children:
                if sub.type == "identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
    return defs


def _resolve_kotlin_import(raw: str, source_file: str, repo_dir: str) -> str | None:
    path = raw.replace(".", "/")
    src_prefixes = [
        os.path.join(repo_dir, "src", "main", "kotlin"),
        os.path.join(repo_dir, "src", "main", "java"),
        os.path.join(repo_dir, "src", "test", "kotlin"),
        os.path.join(repo_dir, "src", "test", "java"),
        repo_dir,
    ]
    for prefix in src_prefixes:
        for ext in (".kt", ".java"):
            candidate = os.path.join(prefix, path + ext)
            if os.path.isfile(candidate):
                return os.path.relpath(candidate, repo_dir)
        if os.path.isdir(os.path.join(prefix, path)):
            for root, _, files in os.walk(os.path.join(prefix, path)):
                for f in files:
                    if f.endswith((".kt", ".java")):
                        return os.path.relpath(os.path.join(root, f), repo_dir)
    return None


# --- Python ---


def _extract_python_imports(source: bytes, lang: ts.Language) -> list[ImportRef]:
    tree = _parse(source, lang)
    imports: list[ImportRef] = []
    for child in tree.root_node.children:
        if child.type == "import_statement":
            for sub in child.children:
                if sub.type == "dotted_name":
                    raw = source[sub.start_byte:sub.end_byte].decode()
                    imports.append(ImportRef(raw=raw))
                    break
        elif child.type == "import_from_statement":
            for sub in child.children:
                if sub.type == "relative_import":
                    raw = source[sub.start_byte:sub.end_byte].decode()
                    imports.append(ImportRef(raw=raw))
                    break
            else:
                for sub in child.children:
                    if sub.type == "dotted_name":
                        raw = source[sub.start_byte:sub.end_byte].decode()
                        imports.append(ImportRef(raw=raw))
                        break
    return imports


def _extract_python_definitions(source: bytes, lang: ts.Language) -> list[str]:
    tree = _parse(source, lang)
    defs: list[str] = []

    def _walk(node: ts.Node, depth: int = 0) -> None:
        if depth > 6:
            return
        if node.type in ("class_definition", "function_definition"):
            for sub in node.children:
                if sub.type == "identifier":
                    defs.append(source[sub.start_byte:sub.end_byte].decode())
                    break
        for child in node.children:
            _walk(child, depth + 1)

    _walk(tree.root_node)
    return defs


def _resolve_python_import(raw: str, source_file: str, repo_dir: str) -> str | None:
    path = raw.replace(".", "/")
    source_dir = os.path.dirname(source_file)

    candidates: list[str] = []
    candidates.extend([
        os.path.join(repo_dir, source_dir, path + ".py"),
        os.path.join(repo_dir, source_dir, path, "__init__.py"),
    ])
    candidates.extend([
        os.path.join(repo_dir, path + ".py"),
        os.path.join(repo_dir, path, "__init__.py"),
    ])

    for c in candidates:
        full = os.path.normpath(c)
        if os.path.isfile(full):
            return os.path.relpath(full, repo_dir)
    return None


# --- Language registry ---


def _build_language_configs() -> dict[str, LanguageConfig]:
    import tree_sitter_typescript as ts_ts
    import tree_sitter_ruby as ts_rb
    import tree_sitter_swift as ts_sw
    import tree_sitter_kotlin as ts_kt
    import tree_sitter_python as ts_py

    configs: dict[str, LanguageConfig] = {}

    configs["typescript"] = LanguageConfig(
        extensions={".ts"},
        language_fn=ts_ts.language_typescript,
        extract_imports=_extract_ts_imports,
        extract_definitions=_extract_ts_definitions,
        resolve_import=_resolve_ts_import,
    )
    configs["tsx"] = LanguageConfig(
        extensions={".tsx"},
        language_fn=ts_ts.language_tsx,
        extract_imports=_extract_ts_imports,
        extract_definitions=_extract_ts_definitions,
        resolve_import=_resolve_ts_import,
    )
    configs["ruby"] = LanguageConfig(
        extensions={".rb"},
        language_fn=ts_rb.language,
        extract_imports=_extract_ruby_imports,
        extract_definitions=_extract_ruby_definitions,
        resolve_import=_resolve_ruby_import,
    )
    configs["swift"] = LanguageConfig(
        extensions={".swift"},
        language_fn=ts_sw.language,
        extract_imports=_extract_swift_imports,
        extract_definitions=_extract_swift_definitions,
        resolve_import=_resolve_swift_import,
    )
    configs["kotlin"] = LanguageConfig(
        extensions={".kt", ".kts"},
        language_fn=ts_kt.language,
        extract_imports=_extract_kotlin_imports,
        extract_definitions=_extract_kotlin_definitions,
        resolve_import=_resolve_kotlin_import,
    )
    configs["python"] = LanguageConfig(
        extensions={".py"},
        language_fn=ts_py.language,
        extract_imports=_extract_python_imports,
        extract_definitions=_extract_python_definitions,
        resolve_import=_resolve_python_import,
    )
    return configs