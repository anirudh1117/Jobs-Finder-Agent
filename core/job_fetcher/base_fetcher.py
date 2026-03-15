"""Base abstractions and shared utilities for job fetchers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, List

from core.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class BaseJobFetcher(ABC):
    """Abstract base class for platform-specific job fetchers.

    Subclasses are responsible for collecting platform-specific raw data and
    returning normalized job dictionaries. This class provides shared
    normalization, persistence, and logging behavior.
    """

    platform: str = ""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize with an optional database manager dependency."""

        self._db = db_manager or DatabaseManager()

    @abstractmethod
    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch jobs from a specific platform and return normalized records."""

    def normalize_job(self, raw_job: dict[str, Any]) -> dict[str, Any]:
        """Convert platform-specific raw job data into a common schema.

        The normalized structure is:
        {
            "title": str,
            "description": str,
            "platform": str,
            "job_url": str,
            "budget": float,
            "hourly_rate": float,
            "created_at": datetime,
        }

        Args:
            raw_job: Raw platform dictionary with job fields.

        Returns:
            A normalized job dictionary ready for persistence.

        Raises:
            ValueError: If a required field (title or job_url) is missing.
        """

        title = str(raw_job.get("title", "")).strip()
        job_url = str(raw_job.get("job_url", "")).strip()

        if not title:
            raise ValueError("Cannot normalize job without a title.")
        if not job_url:
            raise ValueError("Cannot normalize job without a job_url.")

        description = str(raw_job.get("description", "")).strip()
        platform = str(raw_job.get("platform", self.platform)).strip()

        budget = _safe_float(raw_job.get("budget", 0.0))
        hourly_rate = _safe_float(raw_job.get("hourly_rate", 0.0))

        created_at = raw_job.get("created_at")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)

        return {
            "title": title,
            "description": description,
            "platform": platform,
            "job_url": job_url,
            "budget": budget,
            "hourly_rate": hourly_rate,
            "created_at": created_at,
        }

    def save_jobs(self, jobs: List[dict[str, Any]]) -> int:
        """Persist normalized jobs while preventing duplicates by URL.

        Args:
            jobs: Normalized job dictionaries.

        Returns:
            The number of new jobs inserted.
        """

        saved_count = 0
        for job in jobs:
            try:
                job_url = str(job.get("job_url", "")).strip()
                if not job_url:
                    logger.warning("Skipping job without job_url: %s", job)
                    continue

                if self._db.get_job_by_url(job_url) is not None:
                    continue

                # created_at in the normalized schema is for pipeline metadata;
                # model manages created_at automatically in the DB.
                payload = {
                    key: value
                    for key, value in job.items()
                    if key in {"title", "description", "platform", "job_url", "budget", "hourly_rate"}
                }
                self._db.create_job(payload)
                saved_count += 1
            except Exception:  # noqa: BLE001 - keep fetch pipeline resilient
                logger.exception("Failed to save job: %s", job)

        self.log_fetch_results(self.platform, total_found=len(jobs), saved_count=saved_count)
        return saved_count

    def log_fetch_results(self, platform: str, total_found: int, saved_count: int) -> None:
        """Log job fetch summary metrics for observability.

        Args:
            platform: Source platform name.
            total_found: Number of jobs fetched from source.
            saved_count: Number of new jobs inserted.
        """

        logger.info(
            "Job fetch complete | platform=%s total_found=%d saved=%d skipped=%d",
            platform,
            total_found,
            saved_count,
            max(total_found - saved_count, 0),
        )


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort conversion of arbitrary values to float."""

    try:
        if value is None:
            return default
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("$", "").strip()
            if not cleaned:
                return default
            return float(cleaned)
        return float(value)
    except (TypeError, ValueError):
        return default
