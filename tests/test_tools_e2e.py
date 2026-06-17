import asyncio
import logging
import os
import sys
import unittest

import chromadb
from pydantic_ai import RunContext

from review_bot.backend.container_manager import ContainerManager
from review_bot.backend.git import Git
from review_bot.models import ReviewDeps
from review_bot.rag import build_vector_index
from review_bot.tools import (
    execute_command,
    glob,
    read_file,
    list_files,
    search_code,
    semantic_code_search,
)

logger = logging.getLogger("e2e_test")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)


class TestToolsE2E(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = Git(logger, ".")

        cls.container_mgr = ContainerManager(logger)
        cls.container_mgr.setup(cls.backend.repo_dir)

        cls.chroma_client = chromadb.EphemeralClient()
        cls.collection = cls.chroma_client.create_collection("codebase_e2e")
        cls.indexed_count = build_vector_index(cls.backend.repo_dir, cls.collection)

        logger.info(f"E2E Setup: Built vector index with {cls.indexed_count} chunks.")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "container_mgr"):
            cls.container_mgr.cleanup()
        if hasattr(cls, "backend"):
            cls.backend.cleanup()

    def setUp(self):
        self.deps = ReviewDeps(
            mr_request=self.backend,
            container_manager=self.container_mgr,
            mr_description="E2E Test MR",
            vector_index=self.collection,
        )

        class DummyModel:
            pass

        self.ctx = RunContext(
            deps=self.deps,
            model=DummyModel(),
            retry=0,
            tool_name="test",
            usage=None,
            prompt="test",
            messages=[],
        )

    def test_e2e_list_files(self):
        result = list_files(self.ctx, ".")
        self.assertNotIn("Error", result)
        self.assertIn("review_bot", result)
        self.assertIn("pyproject.toml", result)

    def test_e2e_list_files_recursive(self):
        result = list_files(self.ctx, ".", recursive=True)
        self.assertNotIn("Error", result)
        self.assertIn("review_bot", result)
        self.assertIn("pyproject.toml", result)
        self.assertIn("code.py", result)

    def test_e2e_read_file(self):
        result = read_file(self.ctx, "pyproject.toml")
        self.assertNotIn("Error", result)
        self.assertIn('name = "review_bot"', result)

    def test_e2e_search_code(self):
        result = search_code(self.ctx, "review_bot")
        self.assertNotIn("Error", result)
        self.assertIn("pyproject.toml", result)
        self.assertIn("review_bot", result)

    def test_e2e_glob_py_files(self):
        result = glob(self.ctx, "**/*.py")
        self.assertNotIn("Error", result)
        self.assertIn("review_bot", result)
        self.assertIn(".py", result)

    def test_e2e_glob_single_pattern(self):
        result = glob(self.ctx, "pyproject.toml")
        self.assertNotIn("Error", result)
        self.assertIn("pyproject.toml", result)

    def test_e2e_glob_no_match(self):
        result = glob(self.ctx, "*.nonexistent")
        self.assertIn("No files matched", result)

    async def test_e2e_execute_command(self):
        result = await execute_command(self.ctx, "ls -la")
        self.assertNotIn("Error", result)
        self.assertIn("review_bot", result)
        self.assertIn("pyproject.toml", result)

    def test_e2e_semantic_code_search(self):
        if self.indexed_count == 0:
            self.skipTest("No files were indexed, skipping semantic code search test.")

        result = semantic_code_search(self.ctx, "AI Code Review")
        self.assertNotIn("Error", result)
        self.assertNotIn("Vector search is not available", result)
        self.assertIn("File:", result)
        self.assertIn("Similarity:", result)


if __name__ == "__main__":
    unittest.main()
