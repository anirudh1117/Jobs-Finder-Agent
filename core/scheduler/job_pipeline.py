"""Workflow orchestration pipeline for automated freelance job processing."""

from __future__ import annotations

import logging
import traceback
from typing import Dict, List

from django.utils import timezone

from core.applications.application_manager import ApplicationManager
from core.config.constants import JOB_MATCH_THRESHOLD
from core.config.settings import (
    ENABLE_LINKEDIN_FETCH,
    ENABLE_MERCOR_FETCH,
    ENABLE_OUTLIER_FETCH,
    ENABLE_REMOTEOK_FETCH,
    ENABLE_UPWORK_FETCH,
)
from core.database.db_manager import DatabaseManager
from core.database.models import Job, UserJobMatch, UserProfile
from core.job_fetcher import (
    LinkedInFetcher,
    MercorFetcher,
    OutlierFetcher,
    RemoteOKFetcher,
    UpworkFetcher,
)
from core.job_filter.job_classifier import JobClassifier
from core.job_filter.job_scoring import JobScorer
from core.job_filter.skill_matcher import SkillMatcher
from core.logging.system_logger import log_event
from core.notifications.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class JobPipeline:
    """Coordinates end-to-end pipeline stages without owning business logic.

    This class orchestrates existing modules in a deterministic sequence:
    fetch -> store global jobs -> score against each user -> create matches.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize pipeline dependencies and per-run state containers."""

        self._db = db_manager or DatabaseManager()

        self._skill_matcher = SkillMatcher(db_manager=self._db)
        self._classifier = JobClassifier()
        self._scorer = JobScorer()

        self._application_manager = ApplicationManager(db_manager=self._db)
        self._notifier = self._initialize_notifier()

        self._run_started_at = timezone.now()
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

        run_started_at = timezone.now()
        total_saved = 0

        fetchers = []
        if ENABLE_UPWORK_FETCH:
            fetchers.append(UpworkFetcher(db_manager=self._db))
        if ENABLE_MERCOR_FETCH:
            fetchers.append(MercorFetcher(db_manager=self._db))
        if ENABLE_OUTLIER_FETCH:
            fetchers.append(OutlierFetcher(db_manager=self._db))
        if ENABLE_REMOTEOK_FETCH:
            fetchers.append(RemoteOKFetcher(db_manager=self._db))
        if ENABLE_LINKEDIN_FETCH:
            fetchers.append(LinkedInFetcher(db_manager=self._db))

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
                saved_count = fetcher.save_jobs(jobs)
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
        self._notify_pipeline_started()

        try:
            self._run_stage("fetch_jobs", self.fetch_jobs)
            self._run_stage("match_jobs_for_users", self.match_jobs_for_users)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline execution failed for user_id=%s", user_id)
            self._notify_error(str(exc))
            raise
        finally:
            self._notify_daily_summary()
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

        self._fetched_jobs = list(
            Job.objects.filter(id__in=self._new_job_ids_from_check).order_by("-created_at")
        )

        logger.info(
            "Stage fetch_jobs completed | fetched_jobs=%d",
            len(self._fetched_jobs),
        )

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

    def _match_jobs_for_user(self, user_id: int) -> int:
        """Create or update UserJobMatch records for a single user."""

        user_skills = self._skill_matcher.get_user_skills(user_id)
        user_roles = self._get_user_roles(user_id=user_id)
        if not user_skills and not user_roles:
            logger.info("Skipping matching for user_id=%s with no skills/roles", user_id)
            return 0

        match_count = 0
        for job in self._fetched_jobs:
            hourly_rate = float(job.hourly_rate or 0.0)
            budget = float(job.budget or 0.0)
            category = self._classifier.classify_job(
                job_title=job.title,
                job_description=job.description,
                hourly_rate=hourly_rate,
            )

            match_result = self._skill_matcher.match_job_skills(
                job_title=job.title,
                job_description=job.description,
                user_skills=user_skills,
            )
            match_ratio = float(match_result.get("match_ratio", 0.0))
            role_match_score = self._calculate_role_match_score(job=job, user_roles=user_roles)
            keyword_relevance_score = self._calculate_keyword_relevance_score(
                job=job,
                user_skills=user_skills,
                user_roles=user_roles,
            )
            experience_keyword_score = self._calculate_experience_keyword_score(job=job)

            score = self._scorer.calculate_job_score(
                skill_match_ratio=match_ratio,
                role_match_score=role_match_score,
                keyword_relevance_score=keyword_relevance_score,
                experience_keyword_score=experience_keyword_score,
                category=category,
                budget=budget,
                hourly_rate=hourly_rate,
            )

            if score > JOB_MATCH_THRESHOLD:
                self._application_manager.create_or_update_user_job_match(
                    user_id=user_id,
                    job=job,
                    match_score=int(round(score)),
                    application_status=UserJobMatch.ApplicationStatus.NOT_APPLIED,
                )
                match_count += 1
            else:
                logger.info("Job rejected due to low score | user_id=%s title=%s score=%.2f", user_id, job.title, score)
                log_event(
                    level="INFO",
                    module="job_filter",
                    action="reject_job",
                    platform=job.platform,
                    job_url=job.job_url,
                    message="Job rejected due to low score",
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

    def _get_user_roles(self, user_id: int | None) -> list[str]:
        """Return normalized role preferences for the target user when available."""

        if user_id is None:
            return []
        profile = UserProfile.objects.filter(user_id=user_id).order_by("-updated_at").first()
        if profile is None:
            return []
        return [str(role).strip().lower() for role in profile.roles if str(role).strip()]

    @staticmethod
    def _calculate_role_match_score(job: Job, user_roles: list[str]) -> float:
        """Return a role-match component based on role keywords in job text."""

        if not user_roles:
            return 0.0
        job_text = f"{job.title} {job.description}".lower()
        matches = sum(1 for role in user_roles if role in job_text)
        return min(float(matches), 2.0)

    @staticmethod
    def _calculate_keyword_relevance_score(
        job: Job,
        user_skills: list[str],
        user_roles: list[str],
    ) -> float:
        """Return a keyword relevance component based on user/job overlap."""

        relevant_keywords = list(user_skills) + list(user_roles)
        job_text = f"{job.title} {job.description} {' '.join(job.skills or [])}".lower()
        matches = sum(1 for keyword in relevant_keywords if keyword in job_text)
        return min(matches / 2.0, 2.0)

    @staticmethod
    def _calculate_experience_keyword_score(job: Job) -> float:
        """Return an experience-signal component from common experience phrases."""

        experience_keywords = [
            "senior",
            "lead",
            "expert",
            "years of experience",
            "production experience",
            "architecture",
            "scalable systems",
        ]
        job_text = f"{job.title} {job.description}".lower()
        matches = sum(1 for keyword in experience_keywords if keyword in job_text)
        return min(matches / 2.0, 2.0)

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

    def _notify_daily_summary(self) -> None:
        """Send best-effort pipeline summary notification."""

        total_matches = sum(self._user_match_counts.values())
        self._send_notification(
            lambda notifier: notifier.send_daily_summary(
                jobs_scanned=len(self._fetched_jobs),
                relevant_jobs=total_matches,
                auto_applied=0,
                manual_apply=0,
            ),
            "daily summary",
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
