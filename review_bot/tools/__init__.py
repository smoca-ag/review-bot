from pydantic_ai import Tool

from review_bot.tools.execute_command import execute_command
from review_bot.tools.search_code import search_code
from review_bot.tools.view_code_diff_section import view_code_diff_section
from review_bot.tools.list_files import list_files
from review_bot.tools.read_file import read_file
from review_bot.tools.glob import glob
from review_bot.tools.dependency_graph import dependency_graph
from review_bot.tools.suggest_bot_improvement import suggest_bot_improvement
from review_bot.tools.update_todo import update_todo
from review_bot.tools.semantic_code_search import semantic_code_search

shared_tools = [
    Tool(read_file),
    Tool(glob),
    Tool(list_files),
    Tool(search_code),
    Tool(execute_command),
    Tool(semantic_code_search),
    Tool(suggest_bot_improvement),
    Tool(view_code_diff_section),
    Tool(update_todo),
    Tool(dependency_graph),
]
