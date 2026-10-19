import pytest
from stock_agent import (
    INDEX_DEFINITIONS,
    load_index_constituents,
    resolve_name_fallback,
    _looks_like_index_candidate,
    expand_watchlist_entry,
    NIKKEI_225_NAMES,
    INDEX_CONSTITUENT_NAMES,
)


def test_nikkei_225_names_prepopulated():
    assert len(NIKKEI_225_NAMES) >= 200
    assert NIKKEI_225_NAMES.get("9983.T") == "Fast Retailing"
    assert NIKKEI_225_NAMES.get("7203.T") == "Toyota Motor"
    assert NIKKEI_225_NAMES.get("6758.T") == "Sony"
    assert NIKKEI_225_NAMES.get("7974.T") == "Nintendo"


def test_resolve_name_fallback_for_nikkei():
    assert resolve_name_fallback("9983.T") == "Fast Retailing"
    assert resolve_name_fallback("7203.T") == "Toyota Motor"
    assert resolve_name_fallback("6758.T") == "Sony"
    assert resolve_name_fallback("9983") == "Fast Retailing"
    assert resolve_name_fallback("7203") == "Toyota Motor"


def test_sox_index_definition_and_constituents():
    assert "PHLX Semiconductor Sector" in INDEX_DEFINITIONS
    sox_cfg = INDEX_DEFINITIONS["PHLX Semiconductor Sector"]
    assert "SOX" in sox_cfg["aliases"]
    assert "^SOX" in sox_cfg["aliases"]
    assert "SOXX" in sox_cfg["aliases"]
    assert len(sox_cfg["fallback_symbols"]) == 30
    assert "NVDA" in sox_cfg["fallback_symbols"]
    assert "AMD" in sox_cfg["fallback_symbols"]

    constituents = load_index_constituents("PHLX Semiconductor Sector")
    assert len(constituents) == 30
    assert "NVDA" in constituents
    assert "AMD" in constituents
    assert INDEX_CONSTITUENT_NAMES.get("NVDA") == "NVIDIA Corporation"


def test_nbi_index_definition_and_constituents():
    assert "NASDAQ Biotechnology Index" in INDEX_DEFINITIONS
    nbi_cfg = INDEX_DEFINITIONS["NASDAQ Biotechnology Index"]
    assert "NBI" in nbi_cfg["aliases"]
    assert "^NBI" in nbi_cfg["aliases"]
    assert "IBB" in nbi_cfg["aliases"]
    assert len(nbi_cfg["fallback_symbols"]) >= 10
    assert "GILD" in nbi_cfg["fallback_symbols"]

    constituents = load_index_constituents("NASDAQ Biotechnology Index")
    assert len(constituents) >= 20
    assert "GILD" in constituents
    assert "VRTX" in constituents


def test_looks_like_index_candidate_extended():
    assert _looks_like_index_candidate("SOX") is True
    assert _looks_like_index_candidate("PHLX") is True
    assert _looks_like_index_candidate("NBI") is True
    assert _looks_like_index_candidate("NASDAQ BIOTECH") is True
    assert _looks_like_index_candidate("SEMICONDUCTOR") is True
    assert _looks_like_index_candidate("^SOX") is True
    assert _looks_like_index_candidate("AAPL") is False


def test_expand_watchlist_entry_sox_and_nbi():
    expanded_sox = expand_watchlist_entry("SOX")
    assert len(expanded_sox) == 30
    assert "NVDA" in expanded_sox

    expanded_nbi = expand_watchlist_entry("NBI")
    assert len(expanded_nbi) >= 20
    assert "GILD" in expanded_nbi
