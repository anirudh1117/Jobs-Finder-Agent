"""Workflow orchestration pipeline for automated freelance job processing."""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Dict, List

from django.utils import timezone

from core.applications.application_manager import ApplicationManager
from core.config.settings import (
    DEBUG_MODE,
    ENABLE_FREELANCER_FETCH,
    ENABLE_GOOGLE_JOBS_FETCH,
    ENABLE_LINKEDIN_FETCH,
    ENABLE_MERCOR_FETCH,
    ENABLE_OUTLIER_FETCH,
    ENABLE_REMOTEOK_FETCH,
    ENABLE_REMOTIVE_FETCH,
    SCORE_SCALE,
    SCORE_THRESHOLD,
    ENABLE_UPWORK_FETCH,
    ENABLE_WEWORKREMOTELY_FETCH,
)
from core.database.db_manager import DatabaseManager
from core.database.models import Job, UserJobMatch, UserProfile
from core.job_fetcher import (
    FreelancerFetcher,
    GoogleJobsFetcher,
    LinkedInFetcher,
    MercorFetcher,
    OutlierFetcher,
    RemoteOKFetcher,
    RemotiveFetcher,
    UpworkFetcher,
    WeWorkRemotelyFetcher,
)
from core.job_filter.pipeline_debug import JobPreFilter, PipelineDebugReport
from core.job_filter.user_job_relevance import UserJobRelevanceScorer
from core.logging.system_logger import log_event
from core.notifications.telegram_notifier import TelegramNotifier
from core.utils.url_utils import clean_url, is_valid_url, normalize_url

logger = logging.getLogger(__name__)

_SUMMARY_EXPERIENCE_RE = re.compile(r"(\d{1,2})(?:\s*\+)?\s*(?:years|year|yrs|yr)", re.IGNORECASE)


def _extract_experience_years_from_summary(summary: str) -> float:
    """Extract best-effort years-of-experience signal from summary text."""

    match = _SUMMARY_EXPERIENCE_RE.search(str(summary or ""))
    if not match:
        return 0.0

    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


class JobPipeline:
    """Coordinates end-to-end pipeline stages without owning business logic.

    This class orchestrates existing modules in a deterministic sequence:
    fetch -> store global jobs -> score against each user -> create matches.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize pipeline dependencies and per-run state containers."""

        self._db = db_manager or DatabaseManager()

        self._application_manager = ApplicationManager(db_manager=self._db)
        self._notifier = self._initialize_notifier()
        self._debug_mode = DEBUG_MODE
        self._score_scale = SCORE_SCALE
        self._score_threshold = SCORE_THRESHOLD

        self._run_started_at = timezone.now()
        self._run_report = self._new_debug_report()
        self._new_job_ids_from_check: list[int] = []
        self._fetched_jobs: List[Job] = []
        self._filtered_jobs: List[Job] = []
        self._scored_jobs: List[Job] = []
        self._user_match_counts: Dict[int, int] = {}
        self._notified_job_match_ids: set[int] = set()
        self._notified_manual_apply_ids: set[int] = set()

    def check_for_new_jobs(self) -> int:
        """Run a lightweight fetch pass and return newly discovered job count.

        This method fetches jobs from all enabled platforms, persists unique
        jobs globally, and caches newly inserted job IDs for user matching in
        the next pipeline run.
        """

        logger.info("Lightweight job check started")

        self._run_report = self._new_debug_report()

        run_started_at = timezone.now()
        total_saved = 0
        total_scraped = 0

        fetchers = []
        if ENABLE_GOOGLE_JOBS_FETCH:
            fetchers.append(GoogleJobsFetcher(db_manager=self._db))
        if ENABLE_UPWORK_FETCH:
            fetchers.append(UpworkFetcher(db_manager=self._db))
        if ENABLE_MERCOR_FETCH:
            fetchers.append(MercorFetcher(db_manager=self._db))
        if ENABLE_OUTLIER_FETCH:
            fetchers.append(OutlierFetcher(db_manager=self._db))
        if ENABLE_REMOTEOK_FETCH:
            fetchers.append(RemoteOKFetcher(db_manager=self._db))
        if ENABLE_LINKEDIN_FETCH and not ENABLE_GOOGLE_JOBS_FETCH:
            fetchers.append(LinkedInFetcher(db_manager=self._db))
        if ENABLE_REMOTIVE_FETCH:
            fetchers.append(RemotiveFetcher(db_manager=self._db))
        if ENABLE_WEWORKREMOTELY_FETCH:
            fetchers.append(WeWorkRemotelyFetcher(db_manager=self._db))
        if ENABLE_FREELANCER_FETCH:
            fetchers.append(FreelancerFetcher(db_manager=self._db))

        for fetcher in fetchers:
            try:
                log_event(
                    level="INFO",
                    module="job_fetcher",
                    action="fetch_jobs",
                    platform=fetcher.platform,
                    message=f"Fetching jobs from {fetcher.platform.title()}",
                    status="SUCCESS",
                )
                jobs = fetcher.fetch_jobs()
                total_scraped += len(jobs)
                valid_jobs = self._validate_jobs_before_persist(jobs=jobs, platform=fetcher.platform)
                saved_count = fetcher.save_jobs(valid_jobs)
                total_saved += saved_count
                log_event(
                    level="INFO",
                    module="job_fetcher",
                    action="fetch_jobs",
                    platform=fetcher.platform,
                    message=f"Fetched {saved_count} new jobs from {fetcher.platform.title()}",
                    status="SUCCESS",
                )
            except Exception:  # noqa: BLE001
                # Keep scheduler resilient: one fetcher failure should not fail the loop.
                logger.exception(
                    "Lightweight fetch failed for platform=%s", fetcher.platform
                )
                log_event(
                    level="ERROR",
                    module="job_fetcher",
                    action="fetch_jobs",
                    platform=fetcher.platform,
                    message=f"Job fetch failed for {fetcher.platform.title()}",
                    status="FAILED",
                    stack_trace=traceback.format_exc(),
                )

            self._run_report.record_scraped(total_scraped)

        discovered_jobs = list(
            Job.objects.filter(created_at__gte=run_started_at).order_by("-created_at")
        )
        self._new_job_ids_from_check = [job.id for job in discovered_jobs]

        logger.info(
            "Lightweight job check completed | discovered=%d",
            len(self._new_job_ids_from_check),
        )
        log_event(
            level="INFO",
            module="job_fetcher",
            action="check_for_new_jobs",
            message=(
                "Lightweight job check completed "
                f"with discovered={len(self._new_job_ids_from_check)}"
            ),
            status="SUCCESS",
        )

        return len(self._new_job_ids_from_check)

    def run_pipeline(self, user_id: int) -> None:
        """Run global job matching across all active users.

        Args:
            user_id: Legacy scheduler entrypoint identifier. The matching pass
                runs across all active users regardless of this specific value.
        """

        if not self._new_job_ids_from_check:
            logger.info(
                "Pipeline skipped for user_id=%s because no new jobs were detected.",
                user_id,
            )
            log_event(
                level="INFO",
                module="scheduler",
                action="pipeline_skip",
                message=f"Pipeline skipped for user_id={user_id} because no new jobs were detected.",
                status="SUCCESS",
            )
            self._log_run_debug_summary(user_id=user_id)
            self._notify_debug_summary()
            return

        self._reset_run_state(preserve_detected_jobs=True)
        logger.info("Pipeline started for user_id=%s", user_id)
        log_event(
            level="INFO",
            module="scheduler",
            action="pipeline_start",
            message=f"Pipeline started for user_id={user_id}",
            status="SUCCESS",
        )

        try:
            self._run_stage("fetch_jobs", self.fetch_jobs)
            self._run_stage("match_jobs_for_users", self.match_jobs_for_users)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline execution failed for user_id=%s", user_id)
            self._notify_error(str(exc))
            raise
        finally:
            self._log_run_debug_summary(user_id=user_id)
            self._notify_debug_summary()
            # Consume lightweight-check discoveries so each batch is processed once.
            self._new_job_ids_from_check = []

        logger.info(
            "Pipeline finished for user_id=%s | fetched=%d matched_users=%d total_matches=%d",
            user_id,
            len(self._fetched_jobs),
            len(self._user_match_counts),
            sum(self._user_match_counts.values()),
        )
        log_event(
            level="INFO",
            module="scheduler",
            action="pipeline_finish",
            message=(
                f"Pipeline finished for user_id={user_id} "
                f"(fetched={len(self._fetched_jobs)}, matched_users={len(self._user_match_counts)}, "
                f"total_matches={sum(self._user_match_counts.values())})"
            ),
            status="SUCCESS",
        )

    def fetch_jobs(self) -> None:
        """Load globally stored jobs discovered during the lightweight check stage."""

        logger.info("Stage fetch_jobs started")

        staged_jobs = list(
            Job.objects.filter(id__in=self._new_job_ids_from_check).order_by("-created_at")
        )

        self._fetched_jobs = []
        for job in staged_jobs:
            normalized_url = clean_url(normalize_url(job.job_url))
            if not normalized_url or not is_valid_url(normalized_url):
                log_event(
                    level="ERROR",
                    module="scheduler",
                    action="invalid_url",
                    platform=job.platform,
                    job_url=job.job_url,
                    message="Skipping invalid URL while loading staged jobs",
                    status="FAILED",
                )
                continue

            if normalized_url != job.job_url:
                Job.objects.filter(pk=job.pk).update(job_url=normalized_url)
                job.job_url = normalized_url
                log_event(
                    level="INFO",
                    module="scheduler",
                    action="url_normalized",
                    platform=job.platform,
                    job_url=normalized_url,
                    message="Normalized staged job URL",
                    status="SUCCESS",
                )

            self._fetched_jobs.append(job)

        logger.info(
            "Stage fetch_jobs completed | fetched_jobs=%d",
            len(self._fetched_jobs),
        )
        self._log_stage_metrics(stage_name="fetch_jobs")

    def match_jobs_for_users(self) -> None:
        """Score newly fetched jobs against each active user and create matches."""

        logger.info("Stage match_jobs_for_users started")

        active_user_ids = list(
            UserProfile.objects.select_related("user")
            .filter(user__is_active=True)
            .values_list("user_id", flat=True)
            .distinct()
        )

        total_matches = 0
        for auth_user_id in active_user_ids:
            match_count = self._match_jobs_for_user(auth_user_id)
            self._user_match_counts[auth_user_id] = match_count
            total_matches += match_count

        logger.info(
            "Stage match_jobs_for_users completed | users=%d total_matches=%d",
            len(active_user_ids),
            total_matches,
        )
        self._log_stage_metrics(stage_name="match_jobs_for_users")

    def _match_jobs_for_user(self, user_id: int) -> int:
        """Create or update UserJobMatch records for a single user."""

        profile = UserProfile.objects.filter(user_id=user_id).order_by("-updated_at").first()
        if profile is None:
            logger.info("Skipping matching for user_id=%s with no profile", user_id)
            return 0

        user_profile = self._build_user_filter_profile(profile=profile)
        if not user_profile["skills"] and not user_profile["preferred_roles"]:
            logger.info("Skipping matching for user_id=%s with no skills/roles", user_id)
            return 0

        prefilter = JobPreFilter(user_profile=user_profile)
        scorer = UserJobRelevanceScorer(
            user_profile=user_profile,
            scale=self._score_scale,
            threshold=self._score_threshold,
        )

        match_count = 0
        for job in self._fetched_jobs:
            job_input = self._build_job_filter_input(job=job)
            passed_prefilter, prefilter_reason = prefilter.should_score(job_input)
            self._run_report.record_prefilter(
                passed=passed_prefilter,
                reason=prefilter_reason,
            )

            if not passed_prefilter and not self._debug_mode:
                logger.info(
                    "Job removed by prefilter | user_id=%s title=%s reason=%s",
                    user_id,
                    job.title,
                    prefilter_reason,
                )
                continue

            result = scorer.evaluate(job_input)
            score = float(result["score"])
            passed_threshold = result["decision"] == "SAVE"

            reasons: list[str] = []
            if not passed_threshold:
                reasons.append("low_score")
            if result["missing_skills"]:
                reasons.append("missing_skills")
            if not passed_prefilter and prefilter_reason:
                reasons.append(prefilter_reason)

            should_save = self._debug_mode or passed_threshold

            self._run_report.record_scored_job(
                title=job.title,
                job_url=job.job_url,
                score=score,
                matched_skills=list(result["matched_skills"]),
                missing_skills=list(result["missing_skills"]),
                passed_threshold=passed_threshold,
                saved=should_save,
                reasons=reasons,
            )

            if should_save:
                self._application_manager.create_or_update_user_job_match(
                    user_id=user_id,
                    job=job,
                    match_score=int(round(score)),
                    application_status=UserJobMatch.ApplicationStatus.NOT_APPLIED,
                )
                match_count += 1
                if self._debug_mode and not passed_threshold:
                    logger.info(
                        "Job saved because DEBUG_MODE is enabled | user_id=%s title=%s score=%.2f",
                        user_id,
                        job.title,
                        score,
                    )
            else:
                logger.info(
                    "Job discarded by user relevance scorer | user_id=%s title=%s score=%.2f matched=%s missing=%s",
                    user_id,
                    job.title,
                    score,
                    result["matched_skills"],
                    result["missing_skills"],
                )
                log_event(
                    level="INFO",
                    module="job_filter",
                    action="reject_job",
                    platform=job.platform,
                    job_url=job.job_url,
                    message=(
                        "Job discarded by deterministic relevance filter "
                        f"(score={score:.2f}, matched={result['matched_skills']}, "
                        f"missing={result['missing_skills']})"
                    ),
                    response_payload={
                        "reasons": reasons,
                        "threshold": self._score_threshold,
                        "scale": self._score_scale,
                    },
                    status="SUCCESS",
                )

        return match_count

    def _run_stage(self, stage_name: str, stage_fn, *args) -> None:
        """Run a single stage with error isolation and logging."""

        try:
            stage_fn(*args)
        except Exception:  # noqa: BLE001
            logger.exception("Stage failed: %s", stage_name)

    def _reset_run_state(self, preserve_detected_jobs: bool = False) -> None:
        """Reset in-memory stage state for a new pipeline run."""

        self._run_started_at = timezone.now()
        if not preserve_detected_jobs:
            self._new_job_ids_from_check = []
        self._fetched_jobs = []
        self._filtered_jobs = []
        self._scored_jobs = []
        self._user_match_counts = {}

    @staticmethod
    def _build_user_filter_profile(profile: UserProfile) -> dict[str, object]:
        """Build a scorer-friendly user profile dictionary."""

        return {
            "skills": [str(skill).strip() for skill in (profile.skills or []) if str(skill).strip()],
            "experience": _extract_experience_years_from_summary(profile.summary),
            "preferred_roles": [str(role).strip() for role in (profile.roles or []) if str(role).strip()],
            "location": "",
        }

    @staticmethod
    def _build_job_filter_input(job: Job) -> dict[str, object]:
        """Build a scorer-friendly job dictionary from persisted Job rows."""

        return {
            "title": job.title,
            "description": job.description,
            "required_skills": list(job.skills or []),
            "experience_required": None,
            "location": "",
        }

    def _new_debug_report(self) -> PipelineDebugReport:
        """Create a fresh per-run debug report collector."""

        return PipelineDebugReport(
            scale=self._score_scale,
            threshold=self._score_threshold,
            debug_mode=self._debug_mode,
            run_started_at=timezone.now(),
        )

    def _log_run_debug_summary(self, user_id: int) -> None:
        """Emit structured run metrics for observability and debugging."""

        payload = self._run_report.to_payload()
        payload["user_id"] = user_id
        payload["matched_users"] = len(self._user_match_counts)
        payload["total_user_matches"] = sum(self._user_match_counts.values())

        logger.info("pipeline_run_debug %s", json.dumps(payload, sort_keys=True))
        log_event(
            level="INFO",
            module="scheduler",
            action="pipeline_debug_summary",
            message="Pipeline debug summary recorded",
            status="SUCCESS",
            response_payload=payload,
        )

    def _log_stage_metrics(self, stage_name: str) -> None:
        """Emit structured current stage counters for debugging."""

        payload = {
            "stage": stage_name,
            "timestamp": timezone.now().isoformat(),
            "total_jobs_scraped": self._run_report.total_jobs_scraped,
            "jobs_after_prefilter": self._run_report.jobs_after_prefilter,
            "jobs_scored": self._run_report.jobs_scored,
            "jobs_above_threshold": self._run_report.jobs_above_threshold,
            "jobs_saved": self._run_report.jobs_saved,
        }
        logger.info("pipeline_stage_metrics %s", json.dumps(payload, sort_keys=True))

    @staticmethod
    def _initialize_notifier() -> TelegramNotifier | None:
        """Create Telegram notifier when configuration is available."""

        try:
            return TelegramNotifier()
        except ValueError as exc:
            logger.warning(
                "Telegram notifier unavailable in JobPipeline; notifications disabled. %s",
                exc,
            )
            return None
        except Exception:
            logger.exception(
                "Telegram notifier initialization failed unexpectedly in JobPipeline."
            )
            return None

    def _notify_pipeline_started(self) -> None:
        """Send best-effort notification when pipeline execution begins."""

        self._send_notification(
            lambda notifier: notifier.send_message(
                "⚙️ Pipeline Started\n\n"
                "The freelance agent has started scanning platforms for new jobs."
            ),
            "pipeline start",
        )

    def _notify_high_quality_job(self, job: Job, score: float) -> None:
        """Send a one-time notification for a newly discovered high-quality job."""

        if job.id in self._notified_job_match_ids:
            return

        sent = self._send_notification(
            lambda notifier: notifier.send_job_match_notification(job=job, score=score),
            f"high-quality job job_id={job.id}",
        )
        if sent:
            self._notified_job_match_ids.add(job.id)

    def _notify_manual_apply_required(self, job: Job, score: float) -> None:
        """Send a one-time manual-apply-required alert for a job."""

        if job.id in self._notified_manual_apply_ids:
            return

        sent = self._send_notification(
            lambda notifier: notifier.send_manual_apply_notification(job=job, score=score),
            f"manual-apply job_id={job.id}",
        )
        if sent:
            self._notified_manual_apply_ids.add(job.id)

    def _notify_debug_summary(self) -> None:
        """Send a single best-effort pipeline debug summary notification."""

        report_message = self._run_report.build_telegram_message()
        self._send_notification(
            lambda notifier: notifier.send_debug_report(report_message),
            "debug summary",
        )

    def _notify_error(self, error_message: str) -> None:
        """Send best-effort critical pipeline error notification."""

        self._send_notification(
            lambda notifier: notifier.send_error_notification(error_message),
            "pipeline error",
        )

    def _send_notification(self, callback, label: str) -> bool:
        """Execute notifier callback safely without crashing the pipeline."""

        if self._notifier is None:
            return False

        try:
            sent = bool(callback(self._notifier))
            if not sent:
                logger.warning("Telegram notification was not sent for %s", label)
            return sent
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send Telegram notification for %s", label)
            return False

    def _validate_jobs_before_persist(
        self,
        *,
        jobs: list[dict[str, object]],
        platform: str,
    ) -> list[dict[str, object]]:
        """Normalize and validate URLs before persistence to prevent broken links."""

        valid_jobs: list[dict[str, object]] = []
        invalid_count = 0

        for job in jobs:
            original_url = str(job.get("job_url") or "").strip()
            normalized_url = clean_url(normalize_url(original_url))
            if not normalized_url:
                invalid_count += 1
                log_event(
                    level="ERROR",
                    module="job_fetcher",
                    action="invalid_url",
                    platform=platform,
                    job_url=original_url,
                    message="URL normalization failed",
                    status="FAILED",
                )
                continue

            if normalized_url != original_url:
                log_event(
                    level="INFO",
                    module="job_fetcher",
                    action="url_normalized",
                    platform=platform,
                    job_url=normalized_url,
                    message="URL normalized before persistence",
                    status="SUCCESS",
                    response_payload={"original": original_url, "normalized": normalized_url},
                )

            if not is_valid_url(normalized_url):
                invalid_count += 1
                log_event(
                    level="ERROR",
                    module="job_fetcher",
                    action="invalid_url",
                    platform=platform,
                    job_url=normalized_url,
                    message="URL not reachable",
                    status="FAILED",
                )
                continue

            validated_job = dict(job)
            validated_job["job_url"] = normalized_url
            valid_jobs.append(validated_job)

        if invalid_count:
            log_event(
                level="INFO",
                module="job_fetcher",
                action="invalid_urls_skipped",
                platform=platform,
                message=f"Skipped {invalid_count} invalid URLs before persistence",
                status="SUCCESS",
                response_payload={"invalid_urls_skipped": invalid_count},
            )

        return valid_jobs
