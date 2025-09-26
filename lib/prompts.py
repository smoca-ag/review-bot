
class Prompts:
    def __init__(self, logger):
        self.logger = logger
    def context_prompt(self, title: str, diff: str, files):
        file_content = "".join([f"**File** : `{path}`\n"
                                f"```\n{content}\n```\n\n"
                                for path, content in files.items()])

        return f"""You are an expert code review AI assistant. Your task is to load, parse, and understand the context of a merge request I am providing below.
First, I will provide the high-level details of the merge request, followed by the complete diff of all changes, and finally the full contents of each file that was modified.
Carefully analyze all the provided information to build a complete understanding of the changes, their purpose, and their impact on the codebase.
Do not provide a review yet. Simply acknowledge that you have received and processed all the information. Once you have confirmed, I will ask you follow-up questions about specific parts of the code.

## 1. Merge Request Details

* **Title:** `{title}`

## 2. Unified Diff of Changes

```diff
{diff}
```

###3. Contents of each File

{file_content}
"""
    def line_prompt(self, path, position, content):
        return f"""Review online this code line using the provided context.

File: `{path}`
Line: `{position}`
Code: `{content.strip()}`

Respond ONLY with JSON adhering to this structure:
{{
  "issues": [
    {{
      "category": "Correctness|Security|Performance|Clarity|Best Practices",
      "severity": "critical|high|medium|low",
      "summary": "concise issue summary",
      "suggestion": "code suggestion",
      "rationale": "reason for suggestion"
    }}
  ]
}}

If no issues, "issues" must be an empty array."""

