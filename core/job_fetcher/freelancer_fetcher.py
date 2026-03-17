"""Fetches projects from Freelancer.com public API and normalizes them."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List

import requests

from core.config.constants import FREELANCER
from core.job_fetcher.base_fetcher import BaseFetcher

logger = logging.getLogger(__name__)

_FREELANCER_API_URL = "https://www.freelancer.com/api/projects/0.1/projects/active/"
_KEYWORDS = ("software development", "web development")


class FreelancerFetcher(BaseFetcher):
    """Fetch active projects from Freelancer.com using public endpoints."""

    platform = FREELANCER

    def fetch_jobs(self) -> List[dict[str, Any]]:
        """Fetch, parse, normalize, and return Freelancer projects."""

        logger.info("Freelancer fetch start")

        all_raw_projects: list[dict[str, Any]] = []
        for keyword in _KEYWORDS:
            projects = _fetch_projects_for_keyword(keyword)
            all_raw_projects.extend(projects)

        jobs: List[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for project in all_raw_projects:
            if not isinstance(project, dict):
                continue

            project_id = project.get("id")
            seo_url = str(project.get("seo_url") or "").strip()
            job_url = _build_project_url(project_id, seo_url)

            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            raw_job = {
                "title": str(project.get("title") or "").strip(),
                "company": "Freelancer Client",
                "description": str(project.get("preview_description") or project.get("description") or "").strip(),
                "job_url": job_url,
                "platform": self.platform,
                "skills": _extract_skill_names(project.get("jobs")),
                "job_type": "freelance",
                "budget": _extract_budget(project),
                "created_at": _parse_timestamp(project.get("submitdate")),
            }

            try:
                jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid Freelancer project: %s", raw_job)

        logger.info("Freelancer fetch success | fetched=%d", len(jobs))
        return jobs


def _fetch_projects_for_keyword(keyword: str) -> list[dict[str, Any]]:
    """Fetch active Freelancer projects for a keyword query."""

    params = {
        "query": keyword,
        "limit": 100,
        "offset": 0,
        "job_details": True,
        "full_description": True,
        "sort_field": "time_updated",
        "or_search_query": True,
    }

    headers = {"User-Agent": "FreelanceAgent/1.0"}
    try:
        response = requests.get(_FREELANCER_API_URL, params=params, headers=headers, timeout=25)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        logger.exception("Freelancer fetch failure for keyword=%s: request failed", keyword)
        return []
    except ValueError:
        logger.exception("Freelancer fetch failure for keyword=%s: invalid JSON", keyword)
        return []

    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    projects = result.get("projects", []) if isinstance(result, dict) else []

    if not isinstance(projects, list):
        logger.warning("Freelancer fetch failure for keyword=%s: invalid projects payload", keyword)
        return []

    return projects


def _build_project_url(project_id: Any, seo_url: str) -> str:
    """Build a canonical Freelancer project URL."""

    if seo_url:
        return f"https://www.freelancer.com{seo_url}"

    if project_id is None:
        return ""

    return f"https://www.freelancer.com/projects/{project_id}"


def _extract_skill_names(value: Any) -> list[str]:
    """Extract Freelancer skill names from job objects."""

    if not isinstance(value, list):
        return []

    skills: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name and name not in skills:
                skills.append(name)
    return skills


def _extract_budget(project: dict[str, Any]) -> float:
    """Extract a best-effort budget value from project info."""

    for key in ("budget", "bidperiod", "minbudget"):
        value = project.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _parse_timestamp(value: Any) -> datetime:
    """Parse UNIX-like timestamp fields to timezone-aware datetime."""

    try:
        if value is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)
