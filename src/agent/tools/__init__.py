"""Read-only BigQuery tools the insights agent calls.

These are plain Python functions in CP-B. The Claude Agent SDK wrappers
(``@tool`` definitions + MCP server) come in CP-C — keeping the data-access
layer SDK-agnostic means we can unit-test it without the agent runtime.
"""

from src.agent.tools.bq_query import QueryTooExpensiveError, run_sql
from src.agent.tools.bq_sample import sample_rows
from src.agent.tools.bq_schema import describe_table
from src.agent.tools.news_search import search_news

__all__ = [
    "QueryTooExpensiveError",
    "describe_table",
    "run_sql",
    "sample_rows",
    "search_news",
]
