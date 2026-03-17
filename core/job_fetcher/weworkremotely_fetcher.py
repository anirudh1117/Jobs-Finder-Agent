"""Fetches jobs from WeWorkRemotely listings and normalizes them."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, List
from xml.etree import ElementTree

import requests

from core.config.constants import WEWORKREMOTELY
from core.job_fetcher.base_fetcher import BaseFetcher

logger = logging.getLogger(__name__)

_WWR_URL = "https://weworkremotely.com/categories/remote-programming-jobs"
_WWR_BASE_URL = "https://weworkremotely.com"
_RSS_NAMESPACES = {"dc": "http://purl.org/dc/elements/1.1/"}


class WeWorkRemotelyFetcher(BaseFetcher):
    """Fetch remote programming jobs from WeWorkRemotely category page."""

    platform = WEWORKREMOTELY

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, scrape, normalize, and return WeWorkRemotely jobs."""

        logger.info("WeWorkRemotely fetch start")

        headers = {"User-Agent": "FreelanceAgent/1.0"}
        try:
            response = requests.get(_WWR_URL, headers=headers, timeout=25)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("WeWorkRemotely fetch failure: request failed")
            return []

        scraped_jobs = _extract_jobs(response.text)
        jobs: List[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for item in scraped_jobs:
            job_url = item.get("job_url", "").strip()
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            raw_job = {
                "title": item.get("title", "").strip(),
                "company": item.get("company", "").strip(),
                "description": item.get("description", "").strip(),
                "job_url": job_url,
                "platform": self.platform,
                "skills": _extract_skills(item.get("title", ""), item.get("description", "")),
                "job_type": "remote",
                "created_at": datetime.now(timezone.utc),
            }

            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid WeWorkRemotely job: %s", raw_job)

        logger.info("WeWorkRemotely fetch success | fetched=%d", len(jobs))
        return jobs


def _extract_jobs(content: str) -> List[dict[str, str]]:
    """Extract jobs from RSS when available, otherwise fallback to HTML parsing."""

    rss_jobs = _extract_jobs_from_rss(content)
    if rss_jobs:
        return rss_jobs
    return _extract_jobs_from_html(content)


def _extract_jobs_from_rss(xml_content: str) -> List[dict[str, str]]:
    """Extract item records from RSS XML payload."""

    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return []

    items = root.findall("./channel/item")
    jobs: List[dict[str, str]] = []

    for item in items:
        title = _xml_text(item, "title")
        job_url = _xml_text(item, "link")
        description = _clean_html_text(_xml_text(item, "description"))
        company = _xml_text(item, "dc:creator")

        if not title or not job_url:
            continue

        jobs.append(
            {
                "title": title,
                "company": company,
                "description": description or f"Remote programming role at {company or 'an employer'}",
                "job_url": job_url,
            }
        )

    return jobs


def _extract_jobs_from_html(html: str) -> List[dict[str, str]]:
    """Extract job cards from WeWorkRemotely category HTML."""

    jobs: List[dict[str, str]] = []
    cards = re.findall(r"<li[^>]*>(.*?)</li>", html, flags=re.DOTALL | re.IGNORECASE)

    for card in cards:
        href_match = re.search(r'href="(/remote-jobs/[^"]+)"', card)
        if not href_match:
            continue

        title_match = re.search(r'<span[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</span>', card, flags=re.DOTALL)
        company_match = re.search(r'<span[^>]*class="[^"]*company[^"]*"[^>]*>(.*?)</span>', card, flags=re.DOTALL)

        title = _clean_html_text(title_match.group(1) if title_match else "")
        company = _clean_html_text(company_match.group(1) if company_match else "")
        job_url = f"{_WWR_BASE_URL}{href_match.group(1)}"

        if not title:
            continue

        jobs.append(
            {
                "title": title,
                "company": company,
                "description": f"Remote programming role at {company or 'an employer'}",
                "job_url": job_url,
            }
        )

    return jobs


def _xml_text(item: ElementTree.Element, tag: str) -> str:
    """Read and strip XML text nodes with optional namespace support."""

    node = item.find(tag, _RSS_NAMESPACES)
    return (node.text or "").strip() if node is not None else ""


def _clean_html_text(value: str) -> str:
    """Strip tags and normalize whitespace from HTML snippets."""

    without_tags = re.sub(r"<[^>]+>", " ", value)
    cleaned = re.sub(r"\s+", " ", unescape(without_tags)).strip()
    return cleaned


def _extract_skills(title: str, description: str) -> list[str]:
    """Infer simple skill tokens from title and description text."""

    haystack = f"{title} {description}".lower()
    known = [
        "python",
        "django",
        "flask",
        "fastapi",
        "javascript",
        "typescript",
        "react",
        "node",
        "aws",
        "docker",
        "kubernetes",
        "sql",
    ]
    return [skill for skill in known if skill in haystack]
