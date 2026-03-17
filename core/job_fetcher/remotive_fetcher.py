"""Fetches jobs from Remotive API and normalizes them."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List

import requests

from core.config.constants import REMOTIVE
from core.job_fetcher.base_fetcher import BaseFetcher

logger = logging.getLogger(__name__)

_REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveFetcher(BaseFetcher):
    """Fetch jobs from Remotive public API."""

    platform = REMOTIVE

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, parse, normalize, and return Remotive jobs."""

        logger.info("Remotive fetch start")

        try:
            response = requests.get(_REMOTIVE_API_URL, timeout=25)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            logger.exception("Remotive fetch failure: request failed")
            return []
        except ValueError:
            logger.exception("Remotive fetch failure: invalid JSON")
            return []

        raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(raw_jobs, list):
            logger.warning("Remotive fetch failure: jobs payload is not a list")
            return []

        jobs: List[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for item in raw_jobs:
            if not isinstance(item, dict):
                continue

            job_url = str(item.get("url") or "").strip()
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            raw_job = {
                "title": str(item.get("title") or "").strip(),
                "company": str(item.get("company_name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "job_url": job_url,
                "platform": self.platform,
                "skills": item.get("tags") or [],
                "job_type": str(item.get("job_type") or "contract").strip().lower(),
                "created_at": _parse_date(item.get("publication_date")),
            }

            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid Remotive job: %s", raw_job)

        logger.info("Remotive fetch success | fetched=%d", len(jobs))
        return jobs


def _parse_date(value: Any) -> datetime:
    """Parse ISO-like publication date strings to timezone-aware datetime."""

    if not value:
        return datetime.now(timezone.utc)

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
