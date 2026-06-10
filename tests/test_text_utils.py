import unittest

from review_bot.text_utils import (
    chunk_text,
    inject_line_numbers,
    is_binary,
    paginate_text,
    resolve_diff_coordinates,
    wrap_in_cdata,
)


class TestTextUtils(unittest.TestCase):
    def test_wrap_in_cdata(self):
        self.assertEqual(wrap_in_cdata("hello"), "<![CDATA[hello]]>")
        self.assertEqual(wrap_in_cdata("]]>"), "<![CDATA[]]]]><![CDATA[>]]>")
        self.assertEqual(wrap_in_cdata(123), "<![CDATA[123]]>")

    def test_inject_line_numbers(self):
        diff_text = """@@ -1,3 +1,4 @@
 line 1
+line 2
-line 3
 line 4"""
        expected = """@@ -1,3 +1,4 @@
   1 |  line 1
   2 | +line 2
-line 3
   3 |  line 4"""
        self.assertEqual(inject_line_numbers(diff_text), expected)

        # Test with no newline at end of file marker
        diff_text_no_newline = """@@ -1,2 +1,2 @@
 line 1
\\ No newline at end of file"""
        expected_no_newline = """@@ -1,2 +1,2 @@
   1 |  line 1
\\ No newline at end of file"""
        self.assertEqual(inject_line_numbers(diff_text_no_newline), expected_no_newline)

    def test_inject_line_numbers_real_diff(self):
        real_diff = """diff --git a/review_bot/rag.py b/review_bot/rag.py
index 743288d..0461b24 100644
--- a/review_bot/rag.py
+++ b/review_bot/rag.py
@@ -29,7 +29,14 @@ def build_vector_index(repo_dir: str, collection) -> int:
         ".md",
     }
     count = 0
-    for root, _, files in os.walk(repo_dir):
+    for root, dirs, files in os.walk(repo_dir):
+        # Exclude common large/hidden directories
+        dirs[:] = [
+            d
+            for d in dirs
+            if not d.startswith(".")
+            and d not in ("__pycache__", "node_modules", "venv", "env")
+        ]
         for f in files:
             ext = os.path.splitext(f)[1].lower()
             if ext not in source_extensions:"""
        expected_real_diff = """diff --git a/review_bot/rag.py b/review_bot/rag.py
index 743288d..0461b24 100644
--- a/review_bot/rag.py
+++ b/review_bot/rag.py
@@ -29,7 +29,14 @@ def build_vector_index(repo_dir: str, collection) -> int:
  29 |          ".md",
  30 |      }
  31 |      count = 0
-    for root, _, files in os.walk(repo_dir):
  32 | +    for root, dirs, files in os.walk(repo_dir):
  33 | +        # Exclude common large/hidden directories
  34 | +        dirs[:] = [
  35 | +            d
  36 | +            for d in dirs
  37 | +            if not d.startswith(".")
  38 | +            and d not in ("__pycache__", "node_modules", "venv", "env")
  39 | +        ]
  40 |          for f in files:
  41 |              ext = os.path.splitext(f)[1].lower()
  42 |              if ext not in source_extensions:"""
        self.assertEqual(inject_line_numbers(real_diff), expected_real_diff)

    def test_inject_line_numbers_multiple_chunks(self):
        complex_diff = """diff --git a/review_bot/review_bot.py b/review_bot/review_bot.py
index c76db87..2818a01 100644
--- a/review_bot/review_bot.py
+++ b/review_bot/review_bot.py
@@ -102,7 +102,6 @@ async def async_review_process(
     mr_request,
     mr_description,
     secure_base_prompt,
-    secure_base_prompt_no_diff,
     post,
     vector_index,
 ):
@@ -124,15 +123,10 @@ async def async_review_process(
         # 💡 CACHE OPTIMIZATION: Tailor the specialty instructions as a suffix appended to the identical base prompt sequence.
         reports = {}
         for agent_def in SUB_AGENTS:
-            prompt_to_use = (
-                secure_base_prompt_no_diff
-                if agent_def.name == "context"
-                else secure_base_prompt
-            )
             res = await run_agent_with_span(
                 agent_def.name,
                 agents[f"{agent_def.name}_agent"],
-                prompt_to_use + agent_def.specialty_prompt,
+                secure_base_prompt + agent_def.specialty_prompt,
                 deps,
             )
             reports[agent_def.name] = res.output"""

        expected_complex_diff = """diff --git a/review_bot/review_bot.py b/review_bot/review_bot.py
index c76db87..2818a01 100644
--- a/review_bot/review_bot.py
+++ b/review_bot/review_bot.py
@@ -102,7 +102,6 @@ async def async_review_process(
 102 |      mr_request,
 103 |      mr_description,
 104 |      secure_base_prompt,
-    secure_base_prompt_no_diff,
 105 |      post,
 106 |      vector_index,
 107 |  ):
@@ -124,15 +123,10 @@ async def async_review_process(
 123 |          # 💡 CACHE OPTIMIZATION: Tailor the specialty instructions as a suffix appended to the identical base prompt sequence.
 124 |          reports = {}
 125 |          for agent_def in SUB_AGENTS:
-            prompt_to_use = (
-                secure_base_prompt_no_diff
-                if agent_def.name == "context"
-                else secure_base_prompt
-            )
 126 |              res = await run_agent_with_span(
 127 |                  agent_def.name,
 128 |                  agents[f"{agent_def.name}_agent"],
-                prompt_to_use + agent_def.specialty_prompt,
 129 | +                secure_base_prompt + agent_def.specialty_prompt,
 130 |                  deps,
 131 |              )
 132 |              reports[agent_def.name] = res.output"""
        self.assertEqual(inject_line_numbers(complex_diff), expected_complex_diff)

    def test_resolve_diff_coordinates(self):
        complex_diff = """diff --git a/review_bot/review_bot.py b/review_bot/review_bot.py
index c76db87..2818a01 100644
--- a/review_bot/review_bot.py
+++ b/review_bot/review_bot.py
@@ -102,7 +102,6 @@ async def async_review_process(
     mr_request,
     mr_description,
     secure_base_prompt,
-    secure_base_prompt_no_diff,
     post,
     vector_index,
 ):
@@ -124,15 +123,10 @@ async def async_review_process(
         # 💡 CACHE OPTIMIZATION: Tailor the specialty instructions as a suffix appended to the identical base prompt sequence.
         reports = {}
         for agent_def in SUB_AGENTS:
-            prompt_to_use = (
-                secure_base_prompt_no_diff
-                if agent_def.name == "context"
-                else secure_base_prompt
-            )
             res = await run_agent_with_span(
                 agent_def.name,
                 agents[f"{agent_def.name}_agent"],
-                prompt_to_use + agent_def.specialty_prompt,
+                secure_base_prompt + agent_def.specialty_prompt,
                 deps,
             )
             reports[agent_def.name] = res.output"""

        # Test an added line (new_line 129). It should return None for old_line
        old_path, old_line = resolve_diff_coordinates(
            complex_diff, "review_bot/review_bot.py", 129
        )
        self.assertEqual(old_path, "review_bot/review_bot.py")
        self.assertIsNone(old_line)

        # Test an unmodified context line in the first chunk (new_line 103)
        # In old file, it was line 103
        old_path, old_line = resolve_diff_coordinates(
            complex_diff, "review_bot/review_bot.py", 103
        )
        self.assertEqual(old_path, "review_bot/review_bot.py")
        self.assertEqual(old_line, 103)

        # Test an unmodified context line AFTER the deletion in the first chunk (new_line 105)
        # In old file, line 105 was `secure_base_prompt_no_diff,` which is deleted.
        # The new line 105 is `post,`, which was line 106 in the old file.
        old_path, old_line = resolve_diff_coordinates(
            complex_diff, "review_bot/review_bot.py", 105
        )
        self.assertEqual(old_path, "review_bot/review_bot.py")
        self.assertEqual(old_line, 106)

        # Test an unmodified context line in the second chunk (new_line 125)
        # In old file, it was line 126
        old_path, old_line = resolve_diff_coordinates(
            complex_diff, "review_bot/review_bot.py", 125
        )
        self.assertEqual(old_path, "review_bot/review_bot.py")
        self.assertEqual(old_line, 126)

        # Test an unmodified context line AFTER the deletions in the second chunk (new_line 126)
        # In old file, line 126 was `res = await run_agent_with_span(`
        # Wait, the deletions were:
        # - prompt_to_use = (
        # -     secure_base_prompt_no_diff
        # -     if agent_def.name == "context"
        # -     else secure_base_prompt
        # - )
        # That's 5 lines deleted.
        # So new line 126 corresponds to old line 126 + 6 = 132.
        old_path, old_line = resolve_diff_coordinates(
            complex_diff, "review_bot/review_bot.py", 126
        )
        self.assertEqual(old_path, "review_bot/review_bot.py")
        self.assertEqual(old_line, 132)

        # Test a file that doesn't exist in the diff
        old_path, old_line = resolve_diff_coordinates(
            complex_diff, "missing_file.py", 10
        )
        self.assertEqual(old_path, "missing_file.py")
        self.assertIsNone(old_line)

        # Test empty diff
        old_path, old_line = resolve_diff_coordinates(
            "", "review_bot/review_bot.py", 10
        )
        self.assertEqual(old_path, "review_bot/review_bot.py")
        self.assertIsNone(old_line)

    def test_chunk_text(self):
        text = "line1\nline2\nline3\nline4\nline5"
        chunks = chunk_text(text, "test.py", chunk_size=3, overlap=1)

        self.assertEqual(len(chunks), 3)

        self.assertEqual(chunks[0][0], "test.py:chunk-0")
        self.assertEqual(chunks[0][1], "line1\nline2\nline3")
        self.assertEqual(chunks[0][2], 1)  # start line

        self.assertEqual(chunks[1][0], "test.py:chunk-2")
        self.assertEqual(chunks[1][1], "line3\nline4\nline5")
        self.assertEqual(chunks[1][2], 3)  # start line

        self.assertEqual(chunks[2][0], "test.py:chunk-4")
        self.assertEqual(chunks[2][1], "line5")
        self.assertEqual(chunks[2][2], 5)  # start line

        # Empty text
        self.assertEqual(chunk_text("", "test.py"), [])

    def test_paginate_text(self):
        text = "line1\nline2\nline3\nline4\nline5"

        # Test basic pagination
        page1 = paginate_text(text, start_line=1, max_lines=2)
        self.assertIn("line1\nline2", page1)
        self.assertIn("truncated", page1)
        self.assertIn("3 more lines", page1)
        self.assertIn("start_line=3", page1)

        # Test line numbers
        page1_numbered = paginate_text(
            text, start_line=1, max_lines=2, add_line_numbers=True
        )
        self.assertIn("   1 | line1", page1_numbered)
        self.assertIn("   2 | line2", page1_numbered)

        # Test line length truncation
        long_line = "a" * 200
        truncated = paginate_text(
            long_line, start_line=1, max_lines=1, max_line_length=10
        )
        self.assertEqual(truncated, "aaaaaaa...")

        # Test end of file (no truncation message)
        page_end = paginate_text(text, start_line=4, max_lines=5)
        self.assertEqual(page_end, "line4\nline5")

    def test_is_binary(self):
        self.assertTrue(is_binary(b"hello\x00world"))
        self.assertFalse(is_binary(b"hello world"))
        self.assertFalse(is_binary("hello world".encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
