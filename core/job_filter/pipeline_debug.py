"""Reusable pipeline debugging, prefiltering, and report formatting utilities."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

_WORD_RE = re.compile(r"[a-z0-9+#.]+")
_IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class JobDebugEntry:
    """Compact per-job evaluation snapshot for debugging and reporting."""

    title: str
    job_url: str
    score: float
    matched_skills: list[str]
    missing_skills: list[str]
    passed_threshold: bool
    saved: bool
    reasons: list[str] = field(default_factory=list)


class JobPreFilter:
    """Cheap deterministic prefilter to skip obviously irrelevant jobs."""

    def __init__(self, user_profile: dict[str, Any]) -> None:
        phrases = list(user_profile.get("skills") or []) + list(
            user_profile.get("preferred_roles") or []
        )
        self._phrases = [_normalize_text(str(phrase)) for phrase in phrases if str(phrase).strip()]
        self._token_sets = [_tokenize(phrase) for phrase in self._phrases]

    def should_score(self, job_data: dict[str, Any]) -> tuple[bool, str | None]:
        """Return whether a job should proceed to scoring."""

        text = _normalize_text(
            " ".join(
                [
                    str(job_data.get("title") or ""),
                    str(job_data.get("description") or ""),
                    " ".join(str(skill) for skill in (job_data.get("required_skills") or [])),
                    str(job_data.get("location") or ""),
                ]
            )
        )
        if not text:
            return (False, "prefilter_removed")

        if not self._phrases:
            return (True, None)

        if any(phrase in text for phrase in self._phrases):
            return (True, None)

        text_tokens = _tokenize(text)
        if any(tokens and tokens & text_tokens for tokens in self._token_sets):
            return (True, None)

        return (False, "prefilter_removed")


class PipelineDebugReport:
    """Collect per-run metrics, score distribution, and Telegram-friendly output."""

    def __init__(
        self,
        scale: int,
        threshold: float,
        debug_mode: bool,
        run_started_at: datetime | None = None,
    ) -> None:
        self.scale = scale
        self.threshold = threshold
        self.debug_mode = debug_mode
        self.run_started_at = run_started_at or datetime.now(tz=_IST)

        self.total_jobs_scraped = 0
        self.jobs_after_prefilter = 0
        self.jobs_scored = 0
        self.jobs_above_threshold = 0
        self.jobs_saved = 0

        self.rejected_reasons: Counter[str] = Counter()
        self.score_distribution: dict[str, int] = {
            bucket: 0 for bucket in _distribution_template(scale)
        }
        self._entries: list[JobDebugEntry] = []

    def record_scraped(self, count: int) -> None:
        self.total_jobs_scraped = max(int(count), 0)

    def record_prefilter(self, passed: bool, reason: str | None = None) -> None:
        if passed:
            self.jobs_after_prefilter += 1
        elif reason:
            self.rejected_reasons[reason] += 1

    def record_scored_job(
        self,
        *,
        title: str,
        job_url: str,
        score: float,
        matched_skills: list[str],
        missing_skills: list[str],
        passed_threshold: bool,
        saved: bool,
        reasons: list[str] | None = None,
    ) -> None:
        self.jobs_scored += 1
        if passed_threshold:
            self.jobs_above_threshold += 1
        if saved:
            self.jobs_saved += 1

        bucket = _score_bucket(score=score, scale=self.scale)
        self.score_distribution[bucket] = self.score_distribution.get(bucket, 0) + 1

        entry_reasons = list(reasons or [])
        for reason in entry_reasons:
            self.rejected_reasons[reason] += 1

        self._entries.append(
            JobDebugEntry(
                title=title,
                job_url=str(job_url).strip(),
                score=round(float(score), 2),
                matched_skills=list(matched_skills),
                missing_skills=list(missing_skills),
                passed_threshold=passed_threshold,
                saved=saved,
                reasons=entry_reasons,
            )
        )

    def to_payload(self) -> dict[str, Any]:
        """Return structured JSON-friendly payload for logs/storage."""

        top_jobs = [self._entry_to_dict(entry) for entry in self.top_jobs(limit=5)]
        near_miss = [self._entry_to_dict(entry) for entry in self.near_miss(limit=3)]
        above = [self._entry_to_dict(entry) for entry in self.above_threshold_samples(limit=3)]

        payload: dict[str, Any] = {
            "timestamp_ist": self.timestamp_ist,
            "debug_mode": self.debug_mode,
            "score_scale": self.scale,
            "score_threshold": self.threshold,
            "total_jobs_scraped": self.total_jobs_scraped,
            "jobs_after_prefilter": self.jobs_after_prefilter,
            "jobs_scored": self.jobs_scored,
            "jobs_above_threshold": self.jobs_above_threshold,
            "jobs_saved": self.jobs_saved,
            "score_distribution": dict(self.score_distribution),
            "rejected_reasons": dict(self.rejected_reasons),
            "top_jobs": top_jobs,
            "near_miss": near_miss,
            "above_threshold_samples": above,
        }
        if self.debug_mode:
            payload["all_scored_jobs"] = [self._entry_to_dict(entry) for entry in self._sorted_entries()]
        return payload

    @property
    def timestamp_ist(self) -> str:
        return self.run_started_at.astimezone(_IST).strftime("%Y-%m-%d %H:%M:%S IST")

    def top_jobs(self, limit: int) -> list[JobDebugEntry]:
        return self._sorted_entries()[:limit]

    def near_miss(self, limit: int) -> list[JobDebugEntry]:
        entries = [entry for entry in self._sorted_entries() if not entry.passed_threshold]
        return entries[:limit]

    def above_threshold_samples(self, limit: int) -> list[JobDebugEntry]:
        entries = [entry for entry in self._sorted_entries() if entry.passed_threshold]
        return entries[:limit]

    def build_telegram_message(self, max_chars: int = 3900) -> str:
        """Render a single readable Telegram debug report message."""

        lines = [
            f"<b>🛠 Job Debug Report - {escape(self.timestamp_ist)}</b>",
            "",
            f"<b>Scale:</b> {self.scale}",
            f"<b>Threshold:</b> {self.threshold}",
            f"<b>Debug Mode:</b> {'ON' if self.debug_mode else 'OFF'}",
            "",
            f"<b>Scraped:</b> {self.total_jobs_scraped}",
            f"<b>After Pre-filter:</b> {self.jobs_after_prefilter}",
            f"<b>Scored:</b> {self.jobs_scored}",
            f"<b>Above Threshold:</b> {self.jobs_above_threshold}",
            f"<b>Saved:</b> {self.jobs_saved}",
            "",
            "<b>Score Distribution</b>",
        ]

        for bucket, count in self.score_distribution.items():
            lines.append(f"• <b>{escape(bucket)}:</b> {count}")

        lines.extend(["", "<b>Rejected Reasons</b>"])
        if self.rejected_reasons:
            for reason, count in sorted(self.rejected_reasons.items()):
                lines.append(f"• <b>{escape(reason)}:</b> {count}")
        else:
            lines.append("• None")

        self._append_entry_section(lines, "Top Jobs", self.top_jobs(limit=5))
        self._append_entry_section(lines, "Near Miss", self.near_miss(limit=3), include_reason=True)
        self._append_entry_section(lines, "Above Threshold Samples", self.above_threshold_samples(limit=3), include_reason=True)

        if self.debug_mode:
            all_jobs_lines = ["", "<b>All Scored Jobs</b>"]
            for index, entry in enumerate(self._sorted_entries(), start=1):
                marker = "PASS" if entry.passed_threshold else "FAIL"
                all_jobs_lines.append(
                    f"{index}. {escape(entry.title)} <b>{entry.score:.2f}</b> [{marker}]"
                )
            lines.extend(all_jobs_lines)

        message = "\n".join(lines)
        if len(message) <= max_chars:
            return message

        truncated_lines = []
        for line in lines:
            candidate = "\n".join(truncated_lines + [line, "", "<i>Output truncated for Telegram length limit.</i>"])
            if len(candidate) > max_chars:
                break
            truncated_lines.append(line)
        truncated_lines.extend(["", "<i>Output truncated for Telegram length limit.</i>"])
        return "\n".join(truncated_lines)

    def _append_entry_section(
        self,
        lines: list[str],
        heading: str,
        entries: list[JobDebugEntry],
        include_reason: bool = False,
    ) -> None:
        lines.extend(["", f"<b>{escape(heading)}</b>"])
        if not entries:
            lines.append("• None")
            return

        for index, entry in enumerate(entries, start=1):
            lines.append(f"{index}. <b>{escape(entry.title)}</b>")
            lines.append(f"   score: {entry.score:.2f}")
            if entry.job_url:
                lines.append(f"   url: {entry.job_url}")
            if include_reason:
                reason = ", ".join(entry.reasons) if entry.reasons else "passed_threshold"
                lines.append(f"   reason: {escape(reason)}")

    def _sorted_entries(self) -> list[JobDebugEntry]:
        return sorted(self._entries, key=lambda item: (-item.score, item.title.lower()))

    @staticmethod
    def _entry_to_dict(entry: JobDebugEntry) -> dict[str, Any]:
        return {
            "title": entry.title,
            "job_url": entry.job_url,
            "score": entry.score,
            "matched_skills": entry.matched_skills,
            "missing_skills": entry.missing_skills,
            "passed_threshold": entry.passed_threshold,
            "saved": entry.saved,
            "reasons": entry.reasons,
        }


def _distribution_template(scale: int) -> list[str]:
    if scale == 10:
        return ["0-2", "3-4", "5-6", "7-8", "9-10"]
    return ["1", "2", "3", "4", "5"]


def _score_bucket(score: float, scale: int) -> str:
    if scale == 10:
        if score <= 2:
            return "0-2"
        if score <= 4:
            return "3-4"
        if score <= 6:
            return "5-6"
        if score <= 8:
            return "7-8"
        return "9-10"

    rounded = min(max(int(math.ceil(score)), 1), 5)
    return str(rounded)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _tokenize(value: str) -> set[str]:
    return set(_WORD_RE.findall(_normalize_text(value)))
