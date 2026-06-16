from review_bot.models import ReviewDeps
from review_bot.utils.text import paginate_text
from pydantic_ai import RunContext


def _format_dep_graph(graph) -> str:
    lines = [f"Modules: {len(graph.modules)}"]
    total_imports = sum(len(m.imports) for m in graph.modules.values())
    total_deps = sum(len(v) for v in graph.dependents.values())
    lines.append(f"Total imports: {total_imports}, Total dependent edges: {total_deps}")
    for path in sorted(graph.modules):
        m = graph.modules[path]
        deps = graph.dependents.get(path, set())
        lines.append(f"  {path} ({m.language}) — {len(m.imports)} imports, {len(deps)} dependents")
    return "\n".join(lines)


def dependency_graph(
    ctx: RunContext[ReviewDeps],
    file_path: str | None = None,
    direction: str = "dependents",
    symbol: str | None = None,
    start_page: int = 1,
    max_lines: int | None = None,
) -> str:
    """
    Query the dependency graph to find what a file imports or what files depend on it.

    Use this tool to understand the blast radius of a change — which files will be
    affected if a module is modified. Also useful for checking coupling depth.

    Args:
        file_path: Target file to query (e.g. "src/auth.ts"). None returns a summary of all modules.
        direction: "dependents" = files that import this file; "dependencies" = files this file imports.
        symbol: Filter to files that reference a specific exported symbol name.
        start_page: The line number to start reading output from for pagination.
        max_lines: The maximum number of lines of output to return.
    """
    graph = ctx.deps.dependency_graph
    if graph is None:
        return "Dependency graph is not available (not built or build failed)."

    if file_path is None:
        return paginate_text(_format_dep_graph(graph), start_page, max_lines)

    file_path = file_path.lstrip("/")
    mod = graph.modules.get(file_path)
    if mod is None:
        candidates = [p for p in graph.modules if p.endswith(file_path)]
        if len(candidates) == 1:
            file_path = candidates[0]
            mod = graph.modules[file_path]
        elif len(candidates) > 1:
            return f"Multiple matches for '{file_path}': {', '.join(candidates)}. Specify the full path."
        else:
            return f"File not found in dependency graph: {file_path}"

    if direction == "dependents":
        deps = graph.dependents.get(file_path, set())
        if not deps:
            return f"No dependents found for: {file_path}"
        result_lines = [f"Dependents of '{file_path}':"]
        for dep_path in sorted(deps):
            dep_mod = graph.modules.get(dep_path)
            if dep_mod is None:
                result_lines.append(f"  {dep_path}")
                continue
            if symbol:
                matching = [
                    imp.raw for imp in dep_mod.imports
                    if imp.resolved == file_path and symbol.lower() in imp.raw.lower()
                ]
                if not matching:
                    matching = [
                        imp.raw for imp in dep_mod.imports
                        if imp.resolved == file_path
                    ]
                    if not any(symbol.lower() == d.lower() for d in dep_mod.definitions):
                        continue
                result_lines.append(f"  {dep_path} (imports: {', '.join(matching)})")
            else:
                imported = [imp.raw for imp in dep_mod.imports if imp.resolved == file_path]
                suffix = f" (imports: {', '.join(imported)})" if imported else ""
                result_lines.append(f"  {dep_path}{suffix}")
        if len(result_lines) == 1:
            return f"No dependents found for: {file_path}"
        result_lines.append(f"\n{len(result_lines) - 1} files depend on {file_path}.")
        return paginate_text("\n".join(result_lines), start_page, max_lines)

    elif direction == "dependencies":
        if not mod.imports:
            return f"No imports found for: {file_path}"
        result_lines = [f"Dependencies of '{file_path}':"]
        for imp in mod.imports:
            status = imp.resolved if imp.resolved else "[unresolved]"
            result_lines.append(f"  {imp.raw} -> {status}")
        result_lines.append(f"\n{file_path} imports {len(mod.imports)} module(s).")
        return paginate_text("\n".join(result_lines), start_page, max_lines)

    else:
        return f"Invalid direction: '{direction}'. Use 'dependents' or 'dependencies'."