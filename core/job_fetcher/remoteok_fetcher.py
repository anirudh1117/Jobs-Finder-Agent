"""Fetches jobs from RemoteOK public API and normalizes them."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List

import requests

from core.config.constants import REMOTEOK
from core.job_fetcher.base_fetcher import BaseJobFetcher

logger = logging.getLogger(__name__)

_REMOTEOK_API_URL = "https://remoteok.com/api"


class RemoteOKFetcher(BaseJobFetcher):
    """Fetch jobs from RemoteOK's public JSON API."""

    platform = REMOTEOK

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, parse, normalize, and return RemoteOK jobs.

        Returns:
            List of normalized job dictionaries.
        """

        headers = {"User-Agent": "FreelanceAgent/1.0"}

        try:
            response = requests.get(_REMOTEOK_API_URL, headers=headers, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            logger.exception("Failed to fetch RemoteOK API payload.")
            return []
        except ValueError:
            logger.exception("RemoteOK API returned invalid JSON.")
            return []

        if not isinstance(payload, list):
            logger.warning("Unexpected RemoteOK payload type: %s", type(payload))
            return []

        jobs: List[dict[str, Any]] = []
        # RemoteOK includes metadata at index 0; keep only dicts with URL/title.
        for item in payload:
            if not isinstance(item, dict):
                continue

            title = str(item.get("position") or item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title or not url:
                continue

            raw_job = {
                "title": title,
                "description": str(item.get("description") or "").strip(),
                "job_url": url,
                "base_url": "https://remoteok.com",
                "budget": _extract_salary_budget(item),
                "hourly_rate": _extract_hourly_rate(item),
                "platform": self.platform,
                "created_at": _parse_epoch_timestamp(item.get("epoch")),
            }
            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid RemoteOK job: %s", raw_job)

        return jobs


def _extract_salary_budget(item: dict[str, Any]) -> float:
    """Extract salary as a broad budget estimate when available."""

    salary = item.get("salary")
    if salary is None:
        return 0.0

    if isinstance(salary, (int, float)):
        return float(salary)

    if isinstance(salary, str):
        import re

        numbers = re.findall(r"([\d,]+(?:\.\d+)?)", salary)
        if numbers:
            try:
                # Use the larger value as an upper-bound estimate.
                values = [float(num.replace(",", "")) for num in numbers]
                return max(values)
            except ValueError:
                return 0.0

    return 0.0


def _extract_hourly_rate(item: dict[str, Any]) -> float:
    """Estimate hourly rate from salary range if explicit hourly is absent."""

    salary = _extract_salary_budget(item)
    if salary <= 0:
        return 0.0

    # If annual salary is provided, approximate hourly using 2080 work hours.
    if salary > 1000:
        return round(salary / 2080.0, 2)

    return salary


def _parse_epoch_timestamp(epoch_value: Any) -> datetime:
    """Parse UNIX epoch seconds to UTC datetime, fallback to now."""

    try:
        if epoch_value is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(int(epoch_value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)
