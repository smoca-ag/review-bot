"""Tests for build_vector_index file filtering and chunking."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from review_bot.rag import build_vector_index


class TestBuildVectorIndex(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def _index(self, files: dict[str, str]) -> tuple[int, list[str]]:
        """Write *files* into the temp repo and index them with a mock collection.

        Args:
            files: Mapping of relative path to file content.

        Returns:
            The (chunk count, indexed documents) pair.
        """
        for rel, content in files.items():
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        collection = mock.Mock()
        docs: list[str] = []

        def capture_add(**kwargs):
            # Copy at call time: build_vector_index reuses (clears) its
            # batch lists, so recorded call_args would reference empties.
            docs.extend(kwargs["documents"])

        collection.add.side_effect = capture_add
        total = build_vector_index(self.root, collection)
        return total, docs

    def test_file_over_1000_lines_is_indexed(self):
        """Large source files are chunked and indexed, not skipped."""
        content = "\n".join(f"def f{i}(): pass" for i in range(1500))
        total, docs = self._index({"big.py": content})
        self.assertGreater(total, 0)
        self.assertTrue(any("def f1499" in doc for doc in docs))

    def test_file_over_500kb_is_skipped(self):
        content = "x = 1\n" * 100_000  # 600 KB
        self.assertGreater(len(content), 500_000)
        total, docs = self._index({"huge.py": content})
        self.assertEqual(total, 0)
        self.assertEqual(docs, [])

    def test_non_index_extension_is_skipped(self):
        total, docs = self._index({"data.bin": "print('hi')\n" * 10})
        self.assertEqual(total, 0)
        self.assertEqual(docs, [])

    def test_excluded_dirs_are_skipped(self):
        total, docs = self._index({"node_modules/pkg/index.js": "var a = 1;\n"})
        self.assertEqual(total, 0)
        self.assertEqual(docs, [])


if __name__ == "__main__":
    unittest.main()
