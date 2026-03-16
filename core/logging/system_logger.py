"""Reusable centralized logger that persists system events to the database."""

from __future__ import annotations

from typing import Any

from core.database.models import SystemLog


def log_event(
    level: str,
    module: str,
    action: str,
    message: str,
    status: str,
    platform: str | None = None,
    job_url: str | None = None,
    request_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
    stack_trace: str | None = None,
) -> None:
    """Persist a centralized system log record safely.

    Logging must never interrupt business execution, so all persistence errors
    are swallowed by design.
    """

    try:
        SystemLog.objects.create(
            level=level,
            module=module,
            action=action,
            message=message,
            status=status,
            platform=platform,
            job_url=job_url,
            request_payload=request_payload,
            response_payload=response_payload,
            stack_trace=stack_trace,
        )
    except Exception:
        # Intentionally silent to keep logging non-blocking.
        pass
