"""Central helper to load API keys and secrets.

Tries Streamlit secrets first (works on Streamlit Cloud), then falls back to
environment variables and finally to a local .env file if python-dotenv is
available. This keeps local development simple while being Cloud-ready.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def get_secret(*keys: str, default: Any = None) -> Any:
    """Return a secret value looked up by nested keys.

    The lookup order is:
    1. Streamlit secrets (st.secrets) if available.
    2. Environment variables. Nested keys are joined with an underscore, e.g.
       ``alphavantage_api_key`` for ``["alphavantage", "api_key"]``.
    3. A local ``.env`` file loaded via python-dotenv, if installed.

    Parameters
    ----------
    keys:
        One or more keys describing the path to the secret, e.g.
        ``get_secret("finnhub", "api_key")``.
    default:
        Value returned when the secret cannot be found.

    Returns
    -------
    The secret value or ``default``.
    """
    if not keys:
        return default

    # 1. Streamlit secrets
    try:
        import streamlit as st

        value: Any = st.secrets
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                value = None
                break
        if value is not None:
            return value
    except Exception:
        pass

    # 1b. Direct fallback to .streamlit/secrets.toml if running outside Streamlit context
    try:
        import tomllib

        secrets_file = Path(".streamlit/secrets.toml")
        if secrets_file.exists():
            with open(secrets_file, "rb") as f:
                toml_data = tomllib.load(f)
            val = toml_data
            for key in keys:
                if isinstance(val, dict) and key in val:
                    val = val[key]
                else:
                    val = None
                    break
            if val is not None:
                return val
    except Exception:
        pass

    # 2. Environment variables (flat and nested variants)
    env_candidates = [
        "_".join(keys).upper(),
        "_".join(keys).upper() + "_API_KEY",
    ]
    # Also try common legacy names for backwards compatibility
    if keys[0].lower() == "alphavantage":
        env_candidates.append("ALPHAVANTAGE_API_KEY")
    if keys[0].lower() == "finnhub":
        env_candidates.append("FINNHUB_API_KEY")
    if keys[0].lower() == "fred":
        env_candidates.append("FRED_API_KEY")
    if keys[0].lower() == "gemini":
        env_candidates.extend(["GEMINI_API_KEY", "GOOGLE_API_KEY"])

    for candidate in env_candidates:
        value = os.environ.get(candidate)
        if value:
            return value

    # 3. Optional .env file
    try:
        from dotenv import load_dotenv

        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path, override=False)
            for candidate in env_candidates:
                value = os.environ.get(candidate)
                if value:
                    return value
    except Exception:
        pass

    # 3b. Simple fallback parser for .env without requiring python-dotenv
    try:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k in env_candidates and v:
                    return v
    except Exception:
        pass

    return default
