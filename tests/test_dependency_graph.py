import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

import tree_sitter as ts
from pydantic_ai import RunContext

from review_bot.graph import (
    DependencyGraph,
    ImportRef,
    ModuleInfo,
    build_dependency_graph,
)
from review_bot.graph.builder import _detect_language, _get_language_configs
from review_bot.graph.extractors import (
    _extract_kotlin_definitions,
    _extract_kotlin_imports,
    _extract_python_definitions,
    _extract_python_imports,
    _extract_ruby_definitions,
    _extract_ruby_imports,
    _extract_swift_definitions,
    _extract_swift_imports,
    _extract_ts_definitions,
    _extract_ts_imports,
    _resolve_kotlin_import,
    _resolve_python_import,
    _resolve_ruby_import,
    _resolve_swift_import,
    _resolve_ts_import,
)
from review_bot.tools import dependency_graph


class TestTypeScriptParsing(unittest.TestCase):
    def setUp(self):
        cfg = _get_language_configs()["typescript"]
        self.lang = ts.Language(cfg.language_fn())

    def test_extract_imports(self):
        source = b"""import { useState, useEffect } from 'react';
import axios from 'axios';
import * as _ from 'lodash';
import { type User } from './types';
import './setup';
import path from 'path';
"""
        imports = _extract_ts_imports(source, self.lang)
        raws = [i.raw for i in imports]
        self.assertIn("react", raws)
        self.assertIn("axios", raws)
        self.assertIn("lodash", raws)
        self.assertIn("./types", raws)
        self.assertIn("./setup", raws)
        self.assertIn("path", raws)
        self.assertEqual(len(imports), 6)

    def test_extract_definitions(self):
        source = b"""export function login() {}
export class AuthService {}
function helper() {}
class Internal {}
"""
        defs = _extract_ts_definitions(source, self.lang)
        self.assertIn("login", defs)
        self.assertIn("AuthService", defs)
        self.assertIn("helper", defs)
        self.assertIn("Internal", defs)

    def test_empty_file(self):
        source = b""
        self.assertEqual(_extract_ts_imports(source, self.lang), [])
        self.assertEqual(_extract_ts_definitions(source, self.lang), [])

    def test_broken_syntax(self):
        source = b"import { useState } from 'react';\nfunction broken( {"
        imports = _extract_ts_imports(source, self.lang)
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].raw, "react")


class TestTypeScriptResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "src"))
        with open(os.path.join(self.tmpdir, "src", "types.ts"), "w") as f:
            f.write("export type User = { id: string };\n")
        os.makedirs(os.path.join(self.tmpdir, "src", "utils"))
        with open(os.path.join(self.tmpdir, "src", "utils", "index.ts"), "w") as f:
            f.write("export function foo() {}\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_resolve_relative_file(self):
        result = _resolve_ts_import("./types", "src/app.ts", self.tmpdir)
        self.assertEqual(result, os.path.join("src", "types.ts"))

    def test_resolve_relative_with_extension(self):
        with open(os.path.join(self.tmpdir, "src", "helper.ts"), "w") as f:
            f.write("export const x = 1;\n")
        result = _resolve_ts_import("./helper", "src/app.ts", self.tmpdir)
        self.assertEqual(result, os.path.join("src", "helper.ts"))

    def test_resolve_index(self):
        result = _resolve_ts_import("./utils", "src/app.ts", self.tmpdir)
        self.assertEqual(result, os.path.join("src", "utils", "index.ts"))

    def test_unresolvable_bare_import(self):
        result = _resolve_ts_import("react", "src/app.ts", self.tmpdir)
        self.assertIsNone(result)

    def test_unresolvable_path(self):
        result = _resolve_ts_import("./nonexistent", "src/app.ts", self.tmpdir)
        self.assertIsNone(result)


class TestRubyParsing(unittest.TestCase):
    def setUp(self):
        cfg = _get_language_configs()["ruby"]
        self.lang = ts.Language(cfg.language_fn())

    def test_extract_imports(self):
        source = b"""require 'json'
require 'net/http'
require_relative './auth'
require_relative 'services/payment'
"""
        imports = _extract_ruby_imports(source, self.lang)
        raws = [i.raw for i in imports]
        self.assertIn("json", raws)
        self.assertIn("net/http", raws)
        self.assertIn("./auth", raws)
        self.assertIn("services/payment", raws)
        self.assertEqual(len(imports), 4)

    def test_extract_definitions(self):
        source = b"""module MyApp
  class AuthService
    def login(username, password)
    end
  end
end
"""
        defs = _extract_ruby_definitions(source, self.lang)
        self.assertIn("MyApp", defs)
        self.assertIn("AuthService", defs)
        self.assertIn("login", defs)

    def test_no_requires(self):
        source = b"""class Foo
  def bar
  end
end
"""
        self.assertEqual(_extract_ruby_imports(source, self.lang), [])

    def test_broken_syntax(self):
        source = b"require 'json'\nclass Foo\n  def bar\n"
        imports = _extract_ruby_imports(source, self.lang)
        self.assertEqual(len(imports), 1)


class TestRubyResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "services"))
        with open(os.path.join(self.tmpdir, "auth.rb"), "w") as f:
            f.write("class AuthService; end\n")
        with open(os.path.join(self.tmpdir, "services", "payment.rb"), "w") as f:
            f.write("class PaymentService; end\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_resolve_relative(self):
        result = _resolve_ruby_import("./auth", "app.rb", self.tmpdir)
        self.assertEqual(result, "auth.rb")

    def test_resolve_nested_relative(self):
        result = _resolve_ruby_import("services/payment", "app.rb", self.tmpdir)
        self.assertEqual(result, os.path.join("services", "payment.rb"))

    def test_unresolvable(self):
        result = _resolve_ruby_import("nonexistent", "app.rb", self.tmpdir)
        self.assertIsNone(result)


class TestSwiftParsing(unittest.TestCase):
    def setUp(self):
        cfg = _get_language_configs()["swift"]
        self.lang = ts.Language(cfg.language_fn())

    def test_extract_imports(self):
        source = b"""import Foundation
import UIKit
import Alamofire
"""
        imports = _extract_swift_imports(source, self.lang)
        raws = [i.raw for i in imports]
        self.assertIn("Foundation", raws)
        self.assertIn("UIKit", raws)
        self.assertIn("Alamofire", raws)
        self.assertEqual(len(imports), 3)

    def test_extract_definitions(self):
        source = b"""class AuthService {
    func login() {}
}

struct User {
    let id: String
}

enum Role {
    case admin
}

protocol Authenticatable {
    func authenticate()
}
"""
        defs = _extract_swift_definitions(source, self.lang)
        self.assertIn("AuthService", defs)
        self.assertIn("User", defs)
        self.assertIn("Role", defs)
        self.assertIn("login", defs)
        self.assertIn("Authenticatable", defs)

    def test_empty_file(self):
        source = b""
        self.assertEqual(_extract_swift_imports(source, self.lang), [])
        self.assertEqual(_extract_swift_definitions(source, self.lang), [])


class TestSwiftResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "Sources", "Network"))
        with open(os.path.join(self.tmpdir, "Sources", "Network", "Client.swift"), "w") as f:
            f.write("class NetworkClient {}\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_resolve_spm_target(self):
        result = _resolve_swift_import("Network", "Sources/App/Main.swift", self.tmpdir)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("Client.swift"))
        self.assertIn("Network", result)

    def test_unresolvable(self):
        result = _resolve_swift_import("Nonexistent", "Sources/App/Main.swift", self.tmpdir)
        self.assertIsNone(result)


class TestPythonParsing(unittest.TestCase):
    def setUp(self):
        cfg = _get_language_configs()["python"]
        self.lang = ts.Language(cfg.language_fn())

    def test_extract_imports(self):
        source = b"""import os
import sys
from collections import defaultdict
from typing import Optional, List
from .utils import helper
from ..base import BaseClass
import foo.bar.baz
"""
        imports = _extract_python_imports(source, self.lang)
        raws = [i.raw for i in imports]
        self.assertIn("os", raws)
        self.assertIn("sys", raws)
        self.assertIn("collections", raws)
        self.assertIn("typing", raws)
        self.assertIn(".utils", raws)
        self.assertIn("..base", raws)
        self.assertIn("foo.bar.baz", raws)
        self.assertEqual(len(imports), 7)

    def test_extract_definitions(self):
        source = b"""class AuthService:
    def login(self, username, password):
        pass

def helper():
    pass

class User:
    pass
"""
        defs = _extract_python_definitions(source, self.lang)
        self.assertIn("AuthService", defs)
        self.assertIn("helper", defs)
        self.assertIn("User", defs)
        self.assertIn("login", defs)
        self.assertEqual(len(defs), 4)

    def test_no_imports(self):
        source = b"print('hello')\n"
        self.assertEqual(_extract_python_imports(source, self.lang), [])

    def test_broken_syntax(self):
        source = b"import os\nclass Foo\n  def bar(:\n"
        imports = _extract_python_imports(source, self.lang)
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].raw, "os")


class TestPythonResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "pkg"))
        with open(os.path.join(self.tmpdir, "pkg", "__init__.py"), "w") as f:
            f.write("VERSION = '1.0'\n")
        with open(os.path.join(self.tmpdir, "pkg", "utils.py"), "w") as f:
            f.write("def helper(): pass\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_resolve_dotted_module(self):
        result = _resolve_python_import("pkg.utils", "app.py", self.tmpdir)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("utils.py"))

    def test_resolve_package_init(self):
        result = _resolve_python_import("pkg", "app.py", self.tmpdir)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("__init__.py"))

    def test_resolve_relative_from_package(self):
        result = _resolve_python_import("pkg.utils", "pkg/__init__.py", self.tmpdir)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("utils.py"))

    def test_unresolvable_import(self):
        result = _resolve_python_import("nonexistent.module", "app.py", self.tmpdir)
        self.assertIsNone(result)

    def test_resolve_relative_sibling(self):
        result = _resolve_python_import(".utils", "pkg/app.py", self.tmpdir)
        self.assertEqual(result, os.path.join("pkg", "utils.py"))

    def test_resolve_relative_package_init(self):
        result = _resolve_python_import(".", "pkg/app.py", self.tmpdir)
        self.assertEqual(result, os.path.join("pkg", "__init__.py"))

    def test_resolve_relative_parent(self):
        with open(os.path.join(self.tmpdir, "pkg", "shared.py"), "w") as f:
            f.write("SHARED = 1\n")
        result = _resolve_python_import("..shared", "pkg/sub/mod.py", self.tmpdir)
        self.assertEqual(result, os.path.join("pkg", "shared.py"))

    def test_unresolvable_relative_import(self):
        result = _resolve_python_import(".nope", "pkg/app.py", self.tmpdir)
        self.assertIsNone(result)


class TestKotlinParsing(unittest.TestCase):
    def setUp(self):
        cfg = _get_language_configs()["kotlin"]
        self.lang = ts.Language(cfg.language_fn())

    def test_extract_imports(self):
        source = b"""package com.example.app

import kotlinx.coroutines.*
import com.example.utils.Logger
import android.os.Bundle
"""
        imports = _extract_kotlin_imports(source, self.lang)
        raws = [i.raw for i in imports]
        self.assertIn("kotlinx.coroutines", raws)
        self.assertIn("com.example.utils.Logger", raws)
        self.assertIn("android.os.Bundle", raws)
        self.assertEqual(len(imports), 3)

    def test_extract_definitions(self):
        source = b"""class AuthService {
    fun login() {}
}

object Constants {
    const val VERSION = "1.0"
}

fun topLevel() {}
"""
        defs = _extract_kotlin_definitions(source, self.lang)
        self.assertIn("AuthService", defs)
        self.assertIn("Constants", defs)
        self.assertIn("topLevel", defs)

    def test_empty_file(self):
        source = b""
        self.assertEqual(_extract_kotlin_imports(source, self.lang), [])
        self.assertEqual(_extract_kotlin_definitions(source, self.lang), [])


class TestKotlinResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        pkg_dir = os.path.join(self.tmpdir, "src", "main", "kotlin", "com", "example")
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, "Utils.kt"), "w") as f:
            f.write("package com.example\nobject Utils {}\n")
        with open(os.path.join(pkg_dir, "AuthService.kt"), "w") as f:
            f.write("package com.example\nclass AuthService {}\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_resolve_dotted_import(self):
        result = _resolve_kotlin_import("com.example.Utils", "src/main/kotlin/com/example/App.kt", self.tmpdir)
        self.assertIsNotNone(result)
        self.assertIn("Utils.kt", result)

    def test_unresolvable(self):
        result = _resolve_kotlin_import("foo.bar.Baz", "src/main/kotlin/com/example/App.kt", self.tmpdir)
        self.assertIsNone(result)


class TestBuildDependencyGraph(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

        os.makedirs(os.path.join(self.tmpdir, "src"))
        with open(os.path.join(self.tmpdir, "src", "types.ts"), "w") as f:
            f.write("export type User = { id: string };\n")
        with open(os.path.join(self.tmpdir, "src", "app.ts"), "w") as f:
            f.write("import { User } from './types';\nexport function login() {}\n")

        os.makedirs(os.path.join(self.tmpdir, "lib"))
        with open(os.path.join(self.tmpdir, "lib", "auth.rb"), "w") as f:
            f.write("require_relative 'payment'\nclass AuthService; end\n")
        with open(os.path.join(self.tmpdir, "lib", "payment.rb"), "w") as f:
            f.write("class PaymentService; end\n")

        with open(os.path.join(self.tmpdir, "Package.swift"), "w") as f:
            f.write("// swift-tools-version:5.9\n")
        os.makedirs(os.path.join(self.tmpdir, "Sources", "App"))
        with open(os.path.join(self.tmpdir, "Sources", "App", "Main.swift"), "w") as f:
            f.write("import Network\nstruct App {}\n")
        os.makedirs(os.path.join(self.tmpdir, "Sources", "Network"))
        with open(os.path.join(self.tmpdir, "Sources", "Network", "Client.swift"), "w") as f:
            f.write("class NetworkClient {}\n")

        os.makedirs(os.path.join(self.tmpdir, "mylib"))
        with open(os.path.join(self.tmpdir, "mylib", "__init__.py"), "w") as f:
            f.write("VERSION = '1.0'\n")
        with open(os.path.join(self.tmpdir, "mylib", "core.py"), "w") as f:
            f.write("from mylib import VERSION\nclass Core: pass\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_graph_builds(self):
        graph = build_dependency_graph(self.tmpdir)
        self.assertIsInstance(graph, DependencyGraph)
        self.assertGreater(len(graph.modules), 0)

    def test_ts_imports_extracted(self):
        graph = build_dependency_graph(self.tmpdir)
        app_mod = graph.modules.get(os.path.join("src", "app.ts"))
        self.assertIsNotNone(app_mod)
        raws = [i.raw for i in app_mod.imports]
        self.assertIn("./types", raws)

    def test_ts_import_resolved(self):
        graph = build_dependency_graph(self.tmpdir)
        app_mod = graph.modules[os.path.join("src", "app.ts")]
        resolved = [i.resolved for i in app_mod.imports if i.raw == "./types"]
        self.assertTrue(resolved)
        self.assertIsNotNone(resolved[0])

    def test_dependents_index(self):
        graph = build_dependency_graph(self.tmpdir)
        types_path = os.path.join("src", "types.ts")
        deps = graph.dependents.get(types_path, set())
        self.assertIn(os.path.join("src", "app.ts"), deps)

    def test_ruby_imports_extracted(self):
        graph = build_dependency_graph(self.tmpdir)
        auth_mod = graph.modules.get(os.path.join("lib", "auth.rb"))
        self.assertIsNotNone(auth_mod)
        raws = [i.raw for i in auth_mod.imports]
        self.assertIn("payment", raws)

    def test_swift_imports_extracted(self):
        graph = build_dependency_graph(self.tmpdir)
        main_mod = graph.modules.get(os.path.join("Sources", "App", "Main.swift"))
        self.assertIsNotNone(main_mod)
        raws = [i.raw for i in main_mod.imports]
        self.assertIn("Network", raws)

    def test_python_imports_extracted(self):
        graph = build_dependency_graph(self.tmpdir)
        core_mod = graph.modules.get(os.path.join("mylib", "core.py"))
        self.assertIsNotNone(core_mod)
        raws = [i.raw for i in core_mod.imports]
        self.assertIn("mylib", raws)

    def test_python_dependents_index(self):
        graph = build_dependency_graph(self.tmpdir)
        init_path = os.path.join("mylib", "__init__.py")
        deps = graph.dependents.get(init_path, set())
        self.assertIn(os.path.join("mylib", "core.py"), deps)


class TestDetectLanguage(unittest.TestCase):
    def test_ts(self):
        self.assertEqual(_detect_language("app.ts"), "typescript")

    def test_tsx(self):
        self.assertEqual(_detect_language("component.tsx"), "tsx")

    def test_ruby(self):
        self.assertEqual(_detect_language("app.rb"), "ruby")

    def test_swift(self):
        self.assertEqual(_detect_language("Main.swift"), "swift")

    def test_kotlin(self):
        self.assertEqual(_detect_language("App.kt"), "kotlin")

    def test_python(self):
        self.assertEqual(_detect_language("app.py"), "python")

    def test_unknown(self):
        self.assertIsNone(_detect_language("data.json"))


class TestDependencyGraphTool(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

        os.makedirs(os.path.join(self.tmpdir, "src"))
        with open(os.path.join(self.tmpdir, "src", "types.ts"), "w") as f:
            f.write("export type User = { id: string };\n")
        with open(os.path.join(self.tmpdir, "src", "app.ts"), "w") as f:
            f.write("import { User } from './types';\nexport function login() {}\n")

        self.graph = build_dependency_graph(self.tmpdir)

        backend = MagicMock()
        deps = MagicMock()
        deps.mr_request = backend
        deps.mr_description = "test"
        deps.vector_index = None
        deps.dependency_graph = self.graph

        class DummyModel:
            pass

        self.ctx = RunContext(
            deps=deps, model=DummyModel(), retry=0, tool_name="test",
            usage=None, prompt="test", messages=[],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_no_graph(self):
        deps = MagicMock()
        deps.mr_request = MagicMock()
        deps.dependency_graph = None
        class DummyModel:
            pass
        ctx = RunContext(
            deps=deps, model=DummyModel(), retry=0, tool_name="test",
            usage=None, prompt="test", messages=[],
        )
        result = dependency_graph(ctx)
        self.assertIn("not available", result)

    def test_summary(self):
        result = dependency_graph(self.ctx)
        self.assertIn("Modules:", result)

    def test_dependents(self):
        types_path = os.path.join("src", "types.ts")
        result = dependency_graph(self.ctx, file_path=types_path, direction="dependents")
        self.assertIn("app.ts", result)
        self.assertIn("Dependents", result)

    def test_dependencies(self):
        app_path = os.path.join("src", "app.ts")
        result = dependency_graph(self.ctx, file_path=app_path, direction="dependencies")
        self.assertIn("types", result)
        self.assertIn("Dependencies", result)

    def test_nonexistent_file(self):
        result = dependency_graph(self.ctx, file_path="nonexistent.ts")
        self.assertIn("not found", result)

    def test_invalid_direction(self):
        result = dependency_graph(self.ctx, file_path="src/app.ts", direction="invalid")
        self.assertIn("Invalid direction", result)


if __name__ == "__main__":
    unittest.main()
