"""Fetch LinkedIn and Naukri job links via Google-based discovery."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from core.config.constants import GOOGLE, LINKEDIN, NAUKRI
from core.config.settings import GOOGLE_CSE_API_KEY, GOOGLE_CSE_ID, SERPAPI_API_KEY
from core.job_fetcher.base_fetcher import BaseJobFetcher
from core.logging.system_logger import log_event, log_url_event
from core.utils.serpapi_manager import SerpAPIManager
from core.utils.url_utils import clean_url, extract_platform, normalize_url

logger = logging.getLogger(__name__)

_SERPAPI_URL = "https://serpapi.com/search.json"
_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
_GOOGLE_SEARCH_URL = "https://www.google.com/search"

_SEARCH_QUERIES = (
    "python developer remote site:linkedin.com/jobs",
    "backend developer site:naukri.com",
    "django developer remote site:linkedin.com/jobs",
)


class GoogleJobsFetcher(BaseJobFetcher):
    """Discover LinkedIn/Naukri job links from Google search results."""

    platform = GOOGLE

    def fetch_jobs(self) -> list[dict[str, Any]]:
        """Fetch and normalize jobs discovered from Google search providers."""

        log_event(
            level="INFO",
            module="job_fetcher",
            action="google_fetch_start",
            platform=self.platform,
            message="Starting Google-based job discovery",
            status="SUCCESS",
        )

        quota_manager = SerpAPIManager()

        if SERPAPI_API_KEY:
            if not quota_manager.can_make_request():
                quota = quota_manager.get_remaining_quota()
                log_event(
                    level="WARNING",
                    module="serpapi",
                    action="quota_exceeded",
                    platform=self.platform,
                    message="SerpAPI quota exceeded, skipping fetch",
                    status="FAILED",
                    response_payload=quota,
                )
                return []

            search_results = self._search_via_serpapi(manager=quota_manager)
        elif GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID:
            search_results = self._search_via_cse()
        else:
            search_results = self._search_via_html_fallback()

        discovered_urls = 0
        normalized_jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for result in search_results:
            raw_url = str(result.get("job_url") or "")
            normalized = clean_url(normalize_url(raw_url))
            if not normalized or normalized in seen_urls:
                continue

            platform = self._map_platform(normalized)
            if platform is None:
                continue

            if normalized != raw_url.strip():
                log_url_event(
                    module="job_fetcher",
                    action="url_normalized",
                    message="Google result URL normalized",
                    status="SUCCESS",
                    platform=self.platform,
                    job_url=normalized,
                    response_payload={"original": raw_url, "normalized": normalized},
                )

            seen_urls.add(normalized)
            discovered_urls += 1

            raw_job = {
                "title": str(result.get("title") or "Job posting").strip(),
                "description": str(result.get("description") or "").strip(),
                "company": "",
                "job_url": normalized,
                "platform": platform,
                "skills": [],
                "job_type": "contract",
                "budget": 0.0,
                "hourly_rate": 0.0,
                "created_at": datetime.now(timezone.utc),
            }
            try:
                normalized_jobs.append(self.normalize_job(raw_job))
            except ValueError:
                logger.warning("Skipping invalid Google-discovered job: %s", raw_job)

        log_event(
            level="INFO",
            module="job_fetcher",
            action="google_fetch_end",
            platform=self.platform,
            message=f"Google discovery completed with {discovered_urls} URLs",
            status="SUCCESS",
            response_payload={"urls_found": discovered_urls},
        )
        return normalized_jobs

    def _search_via_serpapi(self, manager: SerpAPIManager) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for query in _SEARCH_QUERIES:
            cached = manager.get_cached_results(query)
            if cached is not None:
                log_event(
                    level="INFO",
                    module="serpapi",
                    action="cache_hit",
                    platform=self.platform,
                    message=f"Using cached SerpAPI results for query='{query}'",
                    status="SUCCESS",
                )
                results.extend(cached)
                continue

            if not manager.can_make_request():
                remaining = manager.get_remaining_quota()
                log_event(
                    level="WARNING",
                    module="serpapi",
                    action="quota_exceeded",
                    platform=self.platform,
                    message="SerpAPI quota exceeded during query loop",
                    status="FAILED",
                    response_payload={"query": query, **remaining},
                )
                break

            params = {
                "engine": "google",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "num": 10,
            }
            try:
                response = requests.get(_SERPAPI_URL, params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                logger.exception("SerpAPI request failed for query=%s", query)
                log_event(
                    level="ERROR",
                    module="serpapi",
                    action="request_failed",
                    platform=self.platform,
                    message=f"SerpAPI request failed for query='{query}'",
                    status="FAILED",
                )
                continue

            manager.record_request()
            remaining = manager.get_remaining_quota()
            log_event(
                level="INFO",
                module="serpapi",
                action="request_made",
                platform=self.platform,
                message=(
                    "SerpAPI request made. "
                    f"Remaining daily: {remaining['daily_remaining']}, "
                    f"monthly: {remaining['monthly_remaining']}"
                ),
                status="SUCCESS",
                response_payload={"query": query, **remaining},
            )

            query_results: list[dict[str, str]] = []
            for item in payload.get("organic_results", []) or []:
                if not isinstance(item, dict):
                    continue
                query_results.append(
                    {
                        "title": str(item.get("title") or "").strip(),
                        "job_url": str(item.get("link") or "").strip(),
                        "description": str(item.get("snippet") or "").strip(),
                    }
                )

            manager.cache_results(query, query_results)
            results.extend(query_results)
        return results

    def _search_via_cse(self) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for query in _SEARCH_QUERIES:
            params = {
                "key": GOOGLE_CSE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query,
                "num": 10,
            }
            try:
                response = requests.get(_GOOGLE_CSE_URL, params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                logger.exception("Google CSE request failed for query=%s", query)
                continue

            for item in payload.get("items", []) or []:
                if not isinstance(item, dict):
                    continue
                results.append(
                    {
                        "title": str(item.get("title") or "").strip(),
                        "job_url": str(item.get("link") or "").strip(),
                        "description": str(item.get("snippet") or "").strip(),
                    }
                )
        return results

    def _search_via_html_fallback(self) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        }

        for query in _SEARCH_QUERIES:
            try:
                response = requests.get(
                    _GOOGLE_SEARCH_URL,
                    params={"q": query, "num": 10, "hl": "en"},
                    headers=headers,
                    timeout=20,
                )
                response.raise_for_status()
            except requests.RequestException:
                logger.exception("Google HTML fallback request failed for query=%s", query)
                continue

            results.extend(_extract_google_result_links(response.text))

        return results

    @staticmethod
    def _map_platform(url: str) -> str | None:
        detected = extract_platform(url)
        if detected == "LINKEDIN":
            return LINKEDIN
        if detected == "NAUKRI":
            return NAUKRI
        return None


def _extract_google_result_links(html: str) -> list[dict[str, str]]:
    """Extract result URLs from Google HTML fallback payload."""

    matches = re.findall(r'href="(/url\?q=[^"]+)"', html)
    extracted: list[dict[str, str]] = []

    for raw_href in matches:
        parsed = urlparse(unquote(raw_href))
        query = parse_qs(parsed.query)
        target = str((query.get("q") or [""])[0]).strip()
        if not target:
            continue
        if "linkedin.com" not in target and "naukri.com" not in target:
            continue
        extracted.append({"title": "", "job_url": target, "description": ""})

    return extracted
