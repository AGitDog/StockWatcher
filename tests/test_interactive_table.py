import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

import app


def test_interactive_table_component_files_exist():
    """Verify that components/interactive_table/index.html exists and is non-empty."""
    comp_dir = Path(app.__file__).parent / "components" / "interactive_table"
    assert comp_dir.exists(), "components/interactive_table directory must exist"
    
    index_file = comp_dir / "index.html"
    assert index_file.exists(), "index.html must exist in interactive_table component"
    
    content = index_file.read_text(encoding="utf-8")
    assert "streamlit:componentReady" in content
    assert "streamlit:setComponentValue" in content
    assert "streamlit:setFrameHeight" in content
    assert "searchInput" in content


def test_render_interactive_signals_table_with_mock_component():
    """Verify render_interactive_signals_table passes rows and returns clicked symbol."""
    mock_func = MagicMock(return_value="AAPL")
    
    sample_rows = [
        {"Symbol": "AAPL", "Name": "Apple Inc.", "Brodel": 75},
        {"Symbol": "NVDA", "Name": "NVIDIA Corp.", "Brodel": 88},
    ]

    with patch.object(app, "_interactive_table_func", mock_func):
        result = app.render_interactive_signals_table(sample_rows, selected_symbol="AAPL")
        assert result == "AAPL"
        mock_func.assert_called_once_with(
            rows=sample_rows,
            selected_symbol="AAPL",
            key="main_signals_table",
            default="AAPL",
        )


def test_render_interactive_signals_table_fallback_on_none():
    """Verify render_interactive_signals_table falls back to st.dataframe if component is None."""
    sample_rows = [{"Symbol": "AAPL", "Name": "Apple Inc.", "Brodel": 75}]

    with patch.object(app, "_interactive_table_func", None), \
         patch("streamlit.dataframe") as mock_df:
        result = app.render_interactive_signals_table(sample_rows)
        assert result is None
        mock_df.assert_called_once()


def test_render_interactive_signals_table_fallback_on_exception():
    """Verify render_interactive_signals_table falls back to st.dataframe if component raises error."""
    mock_func = MagicMock(side_effect=Exception("Component render failed"))
    sample_rows = [{"Symbol": "NVDA", "Name": "NVIDIA", "Brodel": 90}]

    with patch.object(app, "_interactive_table_func", mock_func), \
         patch("streamlit.dataframe") as mock_df:
        result = app.render_interactive_signals_table(sample_rows)
        assert result is None
        mock_df.assert_called_once()
