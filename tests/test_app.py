import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Wir fuegen das Projekt-Wurzelverzeichnis zum Pfad hinzu, damit app.py geladen werden kann
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

def test_app_is_loadable():
    """
    Testet, ob app.py fehlerfrei importiert werden kann (keine SyntaxError, IndentationError, etc.).
    """
    try:
        import app
        assert True
    except Exception as e:
        pytest.fail(f"app.py konnte nicht geladen werden. Fehler: {e}")

@patch("app.st")
def test_app_has_help_tab(mock_st):
    """
    Testet, ob die render_stock_agent Funktion die drei Tabs anlegt und keinen Fehler wirft.
    """
    import app
    
    # Mock return values for st.tabs
    mock_tabs = [MagicMock(), MagicMock(), MagicMock()]
    mock_st.tabs.return_value = mock_tabs
    
    try:
        app.render_stock_agent()
        
        # Verify that st.tabs was called with the correct list of tabs
        mock_st.tabs.assert_called_once()
        args, kwargs = mock_st.tabs.call_args
        tab_names = args[0]
        
        assert "Signal Monitor V2" in tab_names
        assert "Watchlist Verwaltung" in tab_names
        assert "Hilfe & Methodik" in tab_names
        
    except Exception as e:
        pytest.fail(f"Fehler beim Rendern der Tabs: {e}")
