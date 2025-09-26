
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
        return f"""You are a meticulous AI code reviewer. Your goal is to provide precise, actionable, and machine-readable feedback.
Using the full merge request context you just processed, perform a detailed review of the following single line of code. Pay close attention to how this line interacts with the code immediately preceding and following it.

* **File Path:** `{path}`
* **Line Number:** `{position}`
* **Line Content:** `{content}`

## Review Instructions & Criteria

Analyze the line against the following criteria, in order of importance:

1.  **Correctness & Bugs:** Bugs, logic errors, or unhandled edge cases.
2.  **Security:** Potential vulnerabilities (e.g., injection, data exposure).
3.  **Performance:** Significant efficiency concerns or bottlenecks.
4.  **Clarity & Maintainability:** Code that is confusing, hard to read, or difficult to maintain.
5.  **Best Practices:** Deviations from language idioms, project conventions, or established principles.

## Severity Levels

Classify any issue you find using one of the following levels:
* **critical:** A definite bug, security vulnerability, or risk of data loss.
* **high:** A major performance issue, significant security concern, or severe deviation from best practices.
* **medium:** Suboptimal code, readability issues, or moderate deviation from best practices.
* **low:** A minor stylistic issue, nitpick, or a small opportunity for improvement.

## Output Format

Provide your review in a valid JSON format. Do not use markdown or any other formatting outside of the JSON structure.

The root object should contain a single key, "issues", which is an array of issue objects. If no issues are found, return an empty array.

Each issue object in the array must have the following structure:
{{
  "category": "Correctness|Security|Performance|Clarity|Best Practices",
  "severity": "critical|high|medium|low",
  "summary": "A brief, one-sentence description of the issue.",
  "suggestion": "The suggested code change as a string.",
  "rationale": "A clear explanation of why the suggestion is an improvement."
}}

**Example for a line with an issue:**
{{
  "issues": [
    {{
      "category": "Performance",
      "severity": "high",
      "summary": "The query retrieves all user fields from the database when only the 'name' is needed.",
      "suggestion": "const user = await db.users.find({{ id: userId }}).select('name');",
      "rationale": "By selecting only the required fields, you reduce the data transfer size from the database and lower memory consumption, which is critical for tables with many columns."
    }}
  ]
}}

**Example for a line with no issues:**
{{
  "issues": []
}}."""

