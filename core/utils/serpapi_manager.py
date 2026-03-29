"""SerpAPI quota and caching manager."""

from __future__ import annotations

from datetime import date
from threading import Lock
from typing import Any

from django.db import DatabaseError, transaction
from django.db.models import Sum
from django.utils import timezone

from core.config.constants import SERPAPI_DAILY_LIMIT, SERPAPI_MONTHLY_LIMIT
from core.database.models import SerpAPIUsage
from core.logging.system_logger import log_event


class SerpAPIManager:
    """Manage SerpAPI request quota with daily/monthly limits and simple daily cache."""

    _cache_lock: Lock = Lock()
    _daily_query_cache: dict[str, list[dict[str, str]]] = {}

    def can_make_request(self) -> bool:
        """Return whether one more request can be made within configured limits."""

        return self._can_make_n_requests(1)

    def record_request(self) -> None:
        """Atomically increment today's request count.

        Database errors are handled safely and never raise to caller.
        """

        today = timezone.localdate()
        month_key = self._month_key(today)

        try:
            with transaction.atomic():
                usage, _ = (
                    SerpAPIUsage.objects.select_for_update()
                    .get_or_create(
                        date=today,
                        defaults={"month": month_key, "request_count": 0},
                    )
                )
                if usage.month != month_key:
                    usage.month = month_key
                usage.request_count = int(usage.request_count) + 1
                usage.save(update_fields=["month", "request_count"])
        except DatabaseError:
            log_event(
                level="ERROR",
                module="serpapi",
                action="record_request_failed",
                message="Failed to persist SerpAPI usage counter",
                status="FAILED",
            )

    def get_remaining_quota(self) -> dict[str, int]:
        """Return remaining daily and monthly request counts."""

        daily_count, monthly_count = self._get_usage_counts()
        return {
            "daily_remaining": max(SERPAPI_DAILY_LIMIT - daily_count, 0),
            "monthly_remaining": max(SERPAPI_MONTHLY_LIMIT - monthly_count, 0),
        }

    def get_cached_results(self, query: str) -> list[dict[str, str]] | None:
        """Return cached results for query executed today, if available."""

        key = self._cache_key(query=query, today=timezone.localdate())
        with self._cache_lock:
            cached = self._daily_query_cache.get(key)
            if cached is None:
                return None
            return [dict(item) for item in cached]

    def cache_results(self, query: str, results: list[dict[str, str]]) -> None:
        """Store query results in an in-memory per-day cache."""

        key = self._cache_key(query=query, today=timezone.localdate())
        with self._cache_lock:
            self._daily_query_cache[key] = [dict(item) for item in results]

    def _can_make_n_requests(self, count: int) -> bool:
        """Return whether count additional requests are within configured limits."""

        daily_count, monthly_count = self._get_usage_counts()
        return (
            daily_count + int(count) <= SERPAPI_DAILY_LIMIT
            and monthly_count + int(count) <= SERPAPI_MONTHLY_LIMIT
        )

    def _get_usage_counts(self) -> tuple[int, int]:
        """Fetch current daily and monthly counts with safe DB handling.

        If DB read fails, this fails closed to avoid accidental overuse.
        """

        today = timezone.localdate()
        month_key = self._month_key(today)

        try:
            daily_count = (
                SerpAPIUsage.objects.filter(date=today)
                .values_list("request_count", flat=True)
                .first()
                or 0
            )

            monthly_count = (
                SerpAPIUsage.objects.filter(month=month_key).aggregate(total=Sum("request_count"))["total"]
                or 0
            )

            return int(daily_count), int(monthly_count)
        except DatabaseError:
            log_event(
                level="ERROR",
                module="serpapi",
                action="read_usage_failed",
                message="Failed to read SerpAPI usage counters",
                status="FAILED",
            )
            # Fail closed: do not risk overusing paid API.
            return SERPAPI_DAILY_LIMIT, SERPAPI_MONTHLY_LIMIT

    @staticmethod
    def _month_key(today: date) -> str:
        return today.strftime("%Y-%m")

    @staticmethod
    def _cache_key(query: str, today: date) -> str:
        return f"{today.isoformat()}::{str(query).strip().lower()}"
