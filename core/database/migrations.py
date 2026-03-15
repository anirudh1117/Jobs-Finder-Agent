"""Utility helpers for initializing the database schema."""

from __future__ import annotations

import logging

from django.core.management import call_command
from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)


def initialize_database() -> bool:
    """Check connectivity, apply migrations, and log initialization status.

    Returns:
        True when the database is reachable and migrations complete
        successfully, otherwise False.
    """

    logger.info("Checking database connectivity.")

    try:
        connection = connections["default"]
        connection.ensure_connection()
    except OperationalError:
        logger.exception("Database connectivity check failed.")
        return False

    logger.info("Database connectivity confirmed. Applying migrations.")

    try:
        call_command("migrate", interactive=False, verbosity=1)
    except Exception:
        logger.exception("Database migration process failed.")
        return False

    logger.info("Database migrations are up to date.")
    return True