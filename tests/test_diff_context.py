import unittest
from unittest.mock import MagicMock

from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from review_bot.models import ReviewDeps
from review_bot.tools import view_code_diff_section


SAMPLE_DIFF = """\
diff --git a/src/auth.py b/src/auth.py
index abc1234..def5678 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,8 @@ def authenticate(username, password):
     user = db.find_user(username)
     if user is None:
         return False
-    if user.password == password:
+    if not verify_password(user.password_hash, password):
+        return False
+    if user.is_locked:
         return False
     return True
diff --git a/src/utils.py b/src/utils.py
index 1111111..2222222 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,3 +1,3 @@
 import os
-import sys
+import pathlib
 import json
"""


def _make_ctx(diff_text: str):
    backend = MagicMock()
    backend.diff.return_value = diff_text
    deps = ReviewDeps(
        mr_request=backend,
        container_manager=MagicMock(),
        mr_description="test",
        vector_index=None,
    )

    return RunContext(
        deps=deps,
        model=MagicMock(spec=Model),
        retry=0,
        tool_name="test",
        usage=RunUsage(),
        prompt="test",
        messages=[],
    )


class TestDiffContextNoDiff(unittest.TestCase):
    def test_empty_diff(self):
        ctx = _make_ctx("")
        result = view_code_diff_section(ctx)
        self.assertIn("No diff available", result)

    def test_none_diff(self):
        backend = MagicMock()
        backend.diff.return_value = None
        deps = ReviewDeps(mr_request=backend, container_manager=MagicMock(), mr_description="test", vector_index=None)

        ctx = RunContext(
            deps=deps, model=MagicMock(spec=Model), retry=0, tool_name="test",
            usage=RunUsage(), prompt="test", messages=[],
        )
        result = view_code_diff_section(ctx)
        self.assertIn("No diff available", result)


class TestDiffContextAllFiles(unittest.TestCase):
    def setUp(self):
        self.ctx = _make_ctx(SAMPLE_DIFF)

    def test_returns_all_files_by_default(self):
        result = view_code_diff_section(self.ctx)
        self.assertIn("src/auth.py", result)
        self.assertIn("src/utils.py", result)

    def test_contains_diff_markers(self):
        result = view_code_diff_section(self.ctx)
        self.assertIn("@@", result)
        self.assertIn("+++ b/", result)


class TestDiffContextFileFilter(unittest.TestCase):
    def setUp(self):
        self.ctx = _make_ctx(SAMPLE_DIFF)

    def test_filter_single_file(self):
        result = view_code_diff_section(self.ctx, file_path="src/auth.py")
        self.assertIn("auth.py", result)
        self.assertNotIn("utils.py", result)

    def test_filter_with_leading_slash(self):
        result = view_code_diff_section(self.ctx, file_path="/src/auth.py")
        self.assertIn("auth.py", result)

    def test_nonexistent_file(self):
        result = view_code_diff_section(self.ctx, file_path="nonexistent.py")
        self.assertIn("No diff found", result)


class TestDiffContextLineRange(unittest.TestCase):
    def setUp(self):
        self.ctx = _make_ctx(SAMPLE_DIFF)

    def test_start_line_filter(self):
        result = view_code_diff_section(self.ctx, file_path="src/auth.py", start_line=14)
        self.assertIn("auth.py", result)

    def test_end_line_filter(self):
        result = view_code_diff_section(self.ctx, file_path="src/auth.py", end_line=12)
        self.assertIn("auth.py", result)

    def test_line_range_no_match(self):
        result = view_code_diff_section(self.ctx, file_path="src/auth.py", start_line=999, end_line=1000)
        self.assertIn("No diff found", result)


class TestDiffContextContextLines(unittest.TestCase):
    def setUp(self):
        self.ctx = _make_ctx(SAMPLE_DIFF)

    def test_zero_context_lines(self):
        result = view_code_diff_section(self.ctx, file_path="src/auth.py", context_lines=0)
        self.assertIn("auth.py", result)

    def test_large_context_lines(self):
        result_small = view_code_diff_section(self.ctx, file_path="src/auth.py", context_lines=1)
        result_large = view_code_diff_section(self.ctx, file_path="src/auth.py", context_lines=10)
        self.assertGreaterEqual(len(result_large), len(result_small))


class TestDiffContextPagination(unittest.TestCase):
    def setUp(self):
        self.ctx = _make_ctx(SAMPLE_DIFF)

    def test_max_lines(self):
        result = view_code_diff_section(self.ctx, max_lines=2)
        self.assertIn("truncated", result)

    def test_start_page(self):
        result = view_code_diff_section(self.ctx, start_page=1, max_lines=100)
        self.assertIn("auth.py", result)


class TestDiffContextNewFile(unittest.TestCase):
    def test_new_file_diff(self):
        diff = (
            "diff --git a/new_file.py b/new_file.py\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
            "--- /dev/null\n"
            "+++ b/new_file.py\n"
            "@@ -0,0 +1,5 @@\n"
            "+import os\n"
            "+\n"
            "+def hello():\n"
            "+    print('hello')\n"
            "+\n"
        )
        ctx = _make_ctx(diff)
        result = view_code_diff_section(ctx, file_path="new_file.py")
        self.assertIn("new_file.py", result)
        self.assertIn("hello", result)

    def test_deleted_file_diff(self):
        diff = (
            "diff --git a/old_file.py b/old_file.py\n"
            "deleted file mode 100644\n"
            "index abc1234..0000000\n"
            "--- a/old_file.py\n"
            "+++ /dev/null\n"
            "@@ -1,3 +0,0 @@\n"
            "-import os\n"
            "-\n"
            "-def goodbye():\n"
        )
        ctx = _make_ctx(diff)
        result = view_code_diff_section(ctx, file_path="old_file.py")
        self.assertIn("old_file.py", result)
        self.assertIn("goodbye", result)


if __name__ == "__main__":
    unittest.main()
