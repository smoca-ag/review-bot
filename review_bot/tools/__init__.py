from pydantic_ai import Tool

from review_bot.tools.code import execute_command, scan_code
from review_bot.tools.diff import diff_context
from review_bot.tools.files import fetch_file_content, list_files
from review_bot.tools.graph import dependency_graph
from review_bot.tools.meta import suggest_bot_improvement
from review_bot.tools.todo import update_todo
from review_bot.tools.vector import vector_search

shared_tools = [
    Tool(fetch_file_content),
    Tool(list_files),
    Tool(scan_code),
    Tool(execute_command),
    Tool(vector_search),
    Tool(suggest_bot_improvement),
    Tool(diff_context),
    Tool(update_todo),
    Tool(dependency_graph),
]
