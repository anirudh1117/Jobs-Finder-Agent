"""Fetches publicly available Outlier job listings and normalizes them."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, List

import requests

from core.config.constants import OUTLIER
from core.job_fetcher.base_fetcher import BaseJobFetcher

logger = logging.getLogger(__name__)

_OUTLIER_JOBS_URL = "https://outlier.ai/careers"


class OutlierFetcher(BaseJobFetcher):
    """Fetch jobs from Outlier public career/listings pages."""

    platform = OUTLIER

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, parse, normalize, and return Outlier jobs.

        Returns:
            List of normalized job dictionaries.
        """

        try:
            response = requests.get(_OUTLIER_JOBS_URL, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch Outlier listings page.")
            return []

        raw_jobs = _extract_jobs_from_page(response.text)
        jobs: List[dict[str, Any]] = []

        for raw in raw_jobs:
            raw_job = {
                "title": raw.get("title") or raw.get("name") or "",
                "description": raw.get("description") or raw.get("summary") or "",
                "job_url": raw.get("url") or raw.get("job_url") or "",
                "base_url": "https://outlier.ai",
                "budget": 0.0,
                "hourly_rate": _extract_hourly_rate(raw),
                "platform": self.platform,
                "created_at": datetime.now(timezone.utc),
            }
            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid Outlier job: %s", raw_job)

        return jobs


def _extract_jobs_from_page(html: str) -> List[dict[str, Any]]:
    """Extract job-like records from embedded JSON-LD script blocks."""

    json_blocks = re.findall(
        r"<script[^>]*type=\"application/ld\+json\"[^>]*>(.*?)</script>",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    jobs: List[dict[str, Any]] = []
    for block in json_blocks:
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict) and payload.get("@type") in {"JobPosting", "Job"}:
            jobs.append(payload)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("@type") in {"JobPosting", "Job"}:
                    jobs.append(item)

    return jobs


def _extract_hourly_rate(raw: dict[str, Any]) -> float:
    """Extract hourly compensation from common text and JSON fields."""

    candidates = [
        raw.get("hourly_rate"),
        raw.get("hourlyRate"),
        raw.get("salary"),
        raw.get("baseSalary"),
        raw.get("description"),
    ]

    for candidate in candidates:
        if candidate is None:
            continue

        if isinstance(candidate, (int, float)):
            return float(candidate)

        if isinstance(candidate, dict):
            numeric = candidate.get("value") or candidate.get("minValue")
            if isinstance(numeric, (int, float)):
                return float(numeric)

        if isinstance(candidate, str):
            match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:/hr|per hour|hour)", candidate, flags=re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    pass

    return 0.0
