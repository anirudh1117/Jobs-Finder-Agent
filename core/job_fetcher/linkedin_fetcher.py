"""Fetches public LinkedIn guest job listings and normalizes them."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, List

import requests

from core.config.constants import LINKEDIN
from core.job_fetcher.base_fetcher import BaseJobFetcher

logger = logging.getLogger(__name__)

_LINKEDIN_GUEST_ENDPOINT = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LINKEDIN_JOB_DETAIL_TEMPLATE = "https://www.linkedin.com/jobs/view/{job_id}/"


class LinkedInFetcher(BaseJobFetcher):
    """Fetch remote freelance-oriented jobs from LinkedIn guest endpoint."""

    platform = LINKEDIN

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch and normalize jobs from LinkedIn's public guest listings.

        Returns:
            List of normalized job dictionaries.
        """

        params = {
            "keywords": "freelance remote",
            "location": "Worldwide",
            "start": 0,
        }

        headers = {"User-Agent": "FreelanceAgent/1.0"}
        try:
            response = requests.get(_LINKEDIN_GUEST_ENDPOINT, params=params, headers=headers, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch LinkedIn guest job listings.")
            return []

        raw_jobs = _extract_jobs_from_html(response.text)
        jobs: List[dict[str, Any]] = []

        for raw in raw_jobs:
            raw_job = {
                "title": raw.get("title", ""),
                "description": raw.get("description", ""),
                "job_url": raw.get("job_url", ""),
                "base_url": "https://www.linkedin.com",
                "budget": 0.0,
                "hourly_rate": 0.0,
                "platform": self.platform,
                "created_at": datetime.now(timezone.utc),
            }
            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid LinkedIn job: %s", raw_job)

        return jobs


def _extract_jobs_from_html(html: str) -> List[dict[str, str]]:
    """Extract simple job records from LinkedIn guest HTML card snippets."""

    title_matches = re.findall(
        r'class="base-search-card__title"[^>]*>(.*?)</h3>',
        html,
        flags=re.DOTALL,
    )
    job_id_matches = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)

    jobs: List[dict[str, str]] = []
    for index, title_raw in enumerate(title_matches):
        title = re.sub(r"\s+", " ", title_raw).strip()
        if not title:
            continue

        job_id = job_id_matches[index] if index < len(job_id_matches) else ""
        job_url = _LINKEDIN_JOB_DETAIL_TEMPLATE.format(job_id=job_id) if job_id else ""

        jobs.append(
            {
                "title": title,
                "description": "",
                "job_url": job_url,
            }
        )

    return jobs
