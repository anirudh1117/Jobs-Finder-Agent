"""Fetches publicly available Mercor job listings and normalizes them."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, List

import requests

from core.config.constants import MERCOR
from core.job_fetcher.base_fetcher import BaseJobFetcher

logger = logging.getLogger(__name__)

_MERCOR_LISTINGS_URL = "https://mercor.com/jobs"


class MercorFetcher(BaseJobFetcher):
    """Fetch jobs from Mercor listings pages/APIs when publicly accessible."""

    platform = MERCOR

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, parse, normalize, and return Mercor jobs.

        This implementation attempts to parse embedded JSON-LD or JSON blobs
        from the public listings page without requiring authentication.

        Returns:
            List of normalized job dictionaries.
        """

        try:
            response = requests.get(_MERCOR_LISTINGS_URL, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch Mercor listings page.")
            return []

        raw_jobs = _extract_jobs_from_page(response.text)
        jobs: List[dict[str, Any]] = []

        for raw in raw_jobs:
            raw_job = {
                "title": raw.get("title") or raw.get("name") or "",
                "description": raw.get("description") or raw.get("summary") or "",
                "job_url": raw.get("url") or raw.get("job_url") or "",
                "budget": 0.0,
                "hourly_rate": _extract_hourly_rate(raw),
                "platform": self.platform,
                "created_at": datetime.now(timezone.utc),
            }
            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid Mercor job: %s", raw_job)

        return jobs


def _extract_jobs_from_page(html: str) -> List[dict[str, Any]]:
    """Best-effort extraction of job dictionaries from page content."""

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
    """Attempt to extract hourly rate from known compensation fields."""

    candidates = [
        raw.get("hourly_rate"),
        raw.get("hourlyRate"),
        raw.get("rate"),
        raw.get("salary"),
        raw.get("baseSalary"),
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
            match = re.search(r"([\d,]+(?:\.\d+)?)", candidate)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    pass

    return 0.0
