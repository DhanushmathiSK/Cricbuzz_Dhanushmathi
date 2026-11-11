"""Settings helper: reads .streamlit/secrets.toml first, then environment variables.

Keeping credentials here (and out of the source code) satisfies the
'secure database credentials and API keys' guideline.
"""
import os

import streamlit as st


def get_setting(name, default=None):
    """Return a setting from secrets.toml or the environment, else `default`."""
    try:
        value = st.secrets[name]
    except Exception:  # missing file, missing key, or no secrets support
        value = os.environ.get(name)
    if value is None:
        return default
    value = str(value).strip()
    return value or default
