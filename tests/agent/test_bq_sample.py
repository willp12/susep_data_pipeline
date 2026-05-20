from unittest.mock import MagicMock

import pytest

from src.agent.tools.bq_sample import sample_rows


def _row(d: dict) -> MagicMock:
    row = MagicMock()
    row.items.return_value = d.items()
    return row


def test_sample_rows_uses_list_rows_not_query() -> None:
    client = MagicMock()
    client.list_rows.return_value = [_row({"a": 1}), _row({"a": 2})]

    result = sample_rows("susep_ses_bronze", "ses_seguros", n=2, client=client)

    assert result["row_count"] == 2
    assert result["rows"] == [{"a": 1}, {"a": 2}]
    assert result["table_id"].endswith("susep_ses_bronze.ses_seguros")
    # Sampling must never run a billable query.
    client.query.assert_not_called()
    _, kwargs = client.list_rows.call_args
    assert kwargs["max_results"] == 2


@pytest.mark.parametrize("bad_n", [0, -1, 101])
def test_sample_rows_validates_n(bad_n: int) -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="n must be between"):
        sample_rows("d", "t", n=bad_n, client=client)
    client.list_rows.assert_not_called()
