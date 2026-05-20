from src.agent.sdk_tools import ALLOWED_TOOLS, SERVER_NAME, build_bq_server


def test_allowed_tools_are_fully_qualified() -> None:
    assert ALLOWED_TOOLS == [
        f"mcp__{SERVER_NAME}__describe_table",
        f"mcp__{SERVER_NAME}__sample_rows",
        f"mcp__{SERVER_NAME}__run_sql",
    ]


def test_build_bq_server_returns_config() -> None:
    server = build_bq_server()
    assert server is not None
