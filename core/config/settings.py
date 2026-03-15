"""Environment-sensitive runtime settings for the Freelance Agent system.

This module contains configuration values that may differ across development,
staging, and production environments. It is intentionally independent from the
Django project settings module so it can be safely imported by services,
scripts, management commands, and future worker processes.
"""

from __future__ import annotations

import os
from typing import Any


def get_env_variable(name: str, default: Any = None) -> Any:
    """Return an environment variable value or the provided default.

    Args:
        name: The environment variable name to read.
        default: The fallback value to return when the variable is missing.

    Returns:
        The environment variable value when present, otherwise the default.
    """

    return os.environ.get(name, default)


def _get_env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable using common truthy values."""

    raw_value = get_env_variable(name)
    if raw_value is None:
        return default

    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


OPENAI_MODEL_NAME: str = get_env_variable("OPENAI_MODEL_NAME", "gpt-4.1-mini")
OPENAI_API_KEY: str | None = get_env_variable("OPENAI_API_KEY")

PLAYWRIGHT_HEADLESS: bool = True
PLAYWRIGHT_TIMEOUT: int = 30000

ENABLE_UPWORK_FETCH: bool = _get_env_bool("ENABLE_UPWORK_FETCH", True)
ENABLE_MERCOR_FETCH: bool = _get_env_bool("ENABLE_MERCOR_FETCH", True)
ENABLE_OUTLIER_FETCH: bool = _get_env_bool("ENABLE_OUTLIER_FETCH", True)
ENABLE_REMOTEOK_FETCH: bool = _get_env_bool("ENABLE_REMOTEOK_FETCH", True)
ENABLE_LINKEDIN_FETCH: bool = _get_env_bool("ENABLE_LINKEDIN_FETCH", True)

ENABLE_JOB_FETCH_LOGGING: bool = _get_env_bool("ENABLE_JOB_FETCH_LOGGING", True)
ENABLE_APPLICATION_LOGGING: bool = _get_env_bool("ENABLE_APPLICATION_LOGGING", True)

TELEGRAM_BOT_TOKEN: str | None = get_env_variable("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str | None = get_env_variable("TELEGRAM_CHAT_ID")

DB_ENGINE: str = get_env_variable("DB_ENGINE", "django.db.backends.postgresql")
DB_NAME: str = get_env_variable("DB_NAME", "freelance_agent")
DB_USER: str = get_env_variable("DB_USER", "")
DB_PASSWORD: str = get_env_variable("DB_PASSWORD", "")
DB_HOST: str = get_env_variable("DB_HOST", "localhost")
DB_PORT: str = get_env_variable("DB_PORT", "5432")