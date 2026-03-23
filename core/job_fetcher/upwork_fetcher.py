"""Fetches public Upwork jobs and normalizes them."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List
from xml.etree import ElementTree

import requests

from core.config.constants import UPWORK
from core.job_fetcher.base_fetcher import BaseJobFetcher

logger = logging.getLogger(__name__)

_UPWORK_RSS_URL = "https://www.upwork.com/ab/feed/jobs/rss"


class UpworkFetcher(BaseJobFetcher):
    """Fetch jobs from Upwork's public RSS feed."""

    platform = UPWORK

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, parse, normalize, and return Upwork jobs.

        Returns:
            List of normalized job dictionaries.
        """

        params = {"q": "python django api", "sort": "recency"}

        try:
            response = requests.get(_UPWORK_RSS_URL, params=params, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch Upwork RSS feed.")
            return []

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError:
            logger.exception("Failed to parse Upwork RSS XML.")
            return []

        jobs: List[dict[str, Any]] = []
        for item in root.findall("./channel/item"):
            raw_job = {
                "title": _xml_text(item, "title"),
                "description": _xml_text(item, "description"),
                "job_url": _xml_text(item, "link"),
                "base_url": "https://www.upwork.com",
                "budget": _extract_budget(_xml_text(item, "description")),
                "hourly_rate": 0.0,
                "platform": self.platform,
                "created_at": datetime.now(timezone.utc),
            }
            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid Upwork job: %s", raw_job)

        return jobs


def _xml_text(item: ElementTree.Element, tag: str) -> str:
    """Return stripped XML child text for a tag."""

    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _extract_budget(description: str) -> float:
    """Extract a rough fixed budget number from feed description text."""

    import re

    match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", description)
    if not match:
        return 0.0

    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0
