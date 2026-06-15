import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from pydantic_ai import RunContext

from review_bot.graph import (
    DependencyGraph,
    ModuleInfo,
    build_dependency_graph,
)
from review_bot.models import ReviewDeps
from review_bot.tools import dependency_graph


class DummyModel:
    pass


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestDependencyGraphE2E(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

        _write(
            os.path.join(self.tmpdir, "src", "models.py"),
            """from typing import Optional
from dataclasses import dataclass
from src.utils import validate

@dataclass
class User:
    id: int
    name: str
""",
        )
        _write(
            os.path.join(self.tmpdir, "src", "utils.py"),
            """import re

def validate(value: str) -> bool:
    return bool(re.match(r'^[a-z]+$', value))
""",
        )
        _write(
            os.path.join(self.tmpdir, "src", "auth.py"),
            """from src.models import User
from src.utils import validate

def authenticate(user: User) -> bool:
    return validate(user.name)
""",
        )
        _write(
            os.path.join(self.tmpdir, "src", "__init__.py"),
            "",
        )

        _write(
            os.path.join(self.tmpdir, "web", "components.ts"),
            """import { useState } from 'react';
import { type User } from './types';
export function Profile() { return null; }
""",
        )
        _write(
            os.path.join(self.tmpdir, "web", "types.ts"),
            "export type User = { id: string; name: string };\n",
        )

        _write(
            os.path.join(self.tmpdir, "rb", "app.rb"),
            """require_relative 'services/auth'
class App; end
""",
        )

        self.graph = build_dependency_graph(self.tmpdir)

        deps = ReviewDeps(
            mr_request=MagicMock(),
            container_manager=MagicMock(),
            mr_description="E2E Test MR",
            vector_index=None,
            dependency_graph=self.graph,
        )
        self.ctx = RunContext(
            deps=deps,
            model=DummyModel(),
            retry=0,
            tool_name="test",
            usage=None,
            prompt="test",
            messages=[],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_graph_built(self):
        self.assertIsInstance(self.graph, DependencyGraph)
        self.assertGreater(len(self.graph.modules), 0)

    def test_python_modules_detected(self):
        python_paths = [p for p in self.graph.modules if p.endswith(".py")]
        self.assertGreaterEqual(len(python_paths), 3)
        self.assertIn(os.path.join("src", "models.py"), self.graph.modules)
        self.assertIn(os.path.join("src", "utils.py"), self.graph.modules)
        self.assertIn(os.path.join("src", "auth.py"), self.graph.modules)

    def test_python_imports_resolved(self):
        auth = self.graph.modules.get(os.path.join("src", "auth.py"))
        self.assertIsNotNone(auth)
        resolved = [i.resolved for i in auth.imports]
        self.assertIn(os.path.join("src", "models.py"), resolved)
        self.assertIn(os.path.join("src", "utils.py"), resolved)

    def test_python_third_party_unresolved(self):
        models = self.graph.modules.get(os.path.join("src", "models.py"))
        typed_resolved = [i.resolved for i in models.imports if i.raw == "typing"]
        for r in typed_resolved:
            self.assertIsNone(r)

    def test_python_dependents(self):
        utils_deps = self.graph.dependents.get(
            os.path.join("src", "utils.py"), set()
        )
        self.assertIn(os.path.join("src", "models.py"), utils_deps)
        self.assertIn(os.path.join("src", "auth.py"), utils_deps)

        models_deps = self.graph.dependents.get(
            os.path.join("src", "models.py"), set()
        )
        self.assertIn(os.path.join("src", "auth.py"), models_deps)

    def test_typescript_modules_detected(self):
        ts_paths = [p for p in self.graph.modules if p.endswith(".ts")]
        self.assertGreaterEqual(len(ts_paths), 1)

    def test_typescript_imports_extracted(self):
        comp = self.graph.modules.get(os.path.join("web", "components.ts"))
        self.assertIsNotNone(comp)
        raws = [i.raw for i in comp.imports]
        self.assertIn("react", raws)
        self.assertIn("./types", raws)

    def test_typescript_dependents(self):
        types_deps = self.graph.dependents.get(
            os.path.join("web", "types.ts"), set()
        )
        self.assertIn(os.path.join("web", "components.ts"), types_deps)

    def test_ruby_modules_detected(self):
        rb_paths = [p for p in self.graph.modules if p.endswith(".rb")]
        self.assertGreaterEqual(len(rb_paths), 1)
        self.assertIn(os.path.join("rb", "app.rb"), self.graph.modules)

    def test_language_labels(self):
        for path, mod in self.graph.modules.items():
            if path.endswith(".py"):
                self.assertEqual(mod.language, "python")
            elif path.endswith(".ts"):
                self.assertEqual(mod.language, "typescript")
            elif path.endswith(".rb"):
                self.assertEqual(mod.language, "ruby")

    def test_definitions_extracted(self):
        utils = self.graph.modules.get(os.path.join("src", "utils.py"))
        self.assertIsNotNone(utils)
        self.assertIn("validate", utils.definitions)

        models = self.graph.modules.get(os.path.join("src", "models.py"))
        self.assertIsNotNone(models)
        self.assertIn("User", models.definitions)

        auth = self.graph.modules.get(os.path.join("src", "auth.py"))
        self.assertIsNotNone(auth)
        self.assertIn("authenticate", auth.definitions)

    def test_empty_init_no_imports(self):
        init_mod = self.graph.modules.get(os.path.join("src", "__init__.py"))
        self.assertIsNotNone(init_mod)
        self.assertEqual(len(init_mod.imports), 0)
        self.assertEqual(len(init_mod.definitions), 0)

    def test_tool_summary(self):
        result = dependency_graph(self.ctx)
        self.assertIn("Modules:", result)
        self.assertIn("Total imports:", result)

    def test_tool_dependents(self):
        result = dependency_graph(
            self.ctx,
            file_path=os.path.join("src", "utils.py"),
            direction="dependents",
        )
        self.assertIn("Dependents", result)
        self.assertIn("auth.py", result)
        self.assertIn("models.py", result)

    def test_tool_dependencies(self):
        result = dependency_graph(
            self.ctx,
            file_path=os.path.join("src", "auth.py"),
            direction="dependencies",
        )
        self.assertIn("Dependencies", result)
        self.assertIn("models.py", result)
        self.assertIn("utils.py", result)

    def test_tool_nonexistent_file(self):
        result = dependency_graph(self.ctx, file_path="nonexistent.py")
        self.assertIn("not found", result)

    def test_ignore_excluded_dirs(self):
        _write(
            os.path.join(self.tmpdir, ".venv", "secret.py"),
            "import os\n",
        )
        _write(
            os.path.join(self.tmpdir, "node_modules", "pkg", "index.ts"),
            "export const x = 1;\n",
        )
        _write(
            os.path.join(self.tmpdir, "__pycache__", "cached.py"),
            "print(1)\n",
        )
        graph = build_dependency_graph(self.tmpdir)
        for p in graph.modules:
            self.assertNotIn(".venv", p)
            self.assertNotIn("node_modules", p)
            self.assertNotIn("__pycache__", p)


if __name__ == "__main__":
    unittest.main()
