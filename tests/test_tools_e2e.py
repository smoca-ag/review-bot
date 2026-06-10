import asyncio
import logging
import os
import sys
import unittest

import chromadb
from pydantic_ai import RunContext

from review_bot.backend.git import Git
from review_bot.models import ReviewDeps
from review_bot.rag import build_vector_index
from review_bot.tools import (
    execute_command,
    fetch_file_content,
    list_files,
    scan_code,
    vector_search,
)

logger = logging.getLogger("e2e_test")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)


class TestToolsE2E(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Set up the Git backend pointing to the current repository
        cls.backend = Git(logger, ".")
        cls.backend.setup_container()

        # Set up ChromaDB and build the vector index
        cls.chroma_client = chromadb.EphemeralClient()
        cls.collection = cls.chroma_client.create_collection("codebase_e2e")
        cls.indexed_count = build_vector_index(cls.backend.repo_dir, cls.collection)

        logger.info(f"E2E Setup: Built vector index with {cls.indexed_count} chunks.")

    @classmethod
    def tearDownClass(cls):
        # Cleanup the container
        if hasattr(cls, "backend"):
            cls.backend.cleanup()

    def setUp(self):
        self.deps = ReviewDeps(
            mr_request=self.backend,
            mr_description="E2E Test MR",
            vector_index=self.collection,
        )

        # We use a dummy model object since RunContext requires it
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

    def test_e2e_fetch_file_content(self):
        result = fetch_file_content(self.ctx, "pyproject.toml")
        self.assertNotIn("Error", result)
        self.assertIn('name = "review_bot"', result)

    def test_e2e_scan_code(self):
        result = scan_code(self.ctx, "review_bot")
        self.assertNotIn("Error", result)
        self.assertIn("pyproject.toml", result)
        self.assertIn("review_bot", result)

    async def test_e2e_execute_command(self):
        result = await execute_command(self.ctx, "ls -la")
        self.assertNotIn("Error", result)
        self.assertIn("review_bot", result)
        self.assertIn("pyproject.toml", result)

    def test_e2e_vector_search(self):
        # Only run if we actually indexed something
        if self.indexed_count == 0:
            self.skipTest("No files were indexed, skipping vector search test.")

        # Search for something that we know is in the codebase
        result = vector_search(self.ctx, "AI Code Review")
        self.assertNotIn("Error", result)
        self.assertNotIn("Vector search is not available", result)
        self.assertIn("File:", result)
        self.assertIn("Similarity:", result)


if __name__ == "__main__":
    unittest.main()
