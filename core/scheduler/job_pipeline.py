"""Workflow orchestration pipeline for automated freelance job processing."""

from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Dict, List

from django.db.models import QuerySet
from django.utils import timezone

from core.auto_apply.apply_engine import ApplyEngine
from core.config.constants import MAX_APPLICATIONS_PER_DAY
from core.config.settings import (
    ENABLE_LINKEDIN_FETCH,
    ENABLE_MERCOR_FETCH,
    ENABLE_OUTLIER_FETCH,
    ENABLE_REMOTEOK_FETCH,
    ENABLE_UPWORK_FETCH,
)
from core.database.db_manager import DatabaseManager
from core.database.models import Application, Job
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
from core.proposal.proposal_builder import ProposalBuilder
from core.proposal.proposal_generator import ProposalGenerator
from core.proposal.proposal_optimizer import ProposalOptimizer

logger = logging.getLogger(__name__)


class JobPipeline:
    """Coordinates end-to-end pipeline stages without owning business logic.

    This class orchestrates existing modules in a deterministic sequence:
    fetch -> filter -> score -> generate proposals -> apply.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize pipeline dependencies and per-run state containers."""

        self._db = db_manager or DatabaseManager()

        self._skill_matcher = SkillMatcher(db_manager=self._db)
        self._classifier = JobClassifier()
        self._scorer = JobScorer()

        self._proposal_builder = ProposalBuilder(db_manager=self._db)
        self._proposal_generator: ProposalGenerator | None = None
        self._proposal_optimizer = ProposalOptimizer()

        self._apply_engine = ApplyEngine(db_manager=self._db)
        self._notifier = self._initialize_notifier()

        self._run_started_at = timezone.now()
        self._new_job_ids_from_check: list[int] = []
        self._fetched_jobs: List[Job] = []
        self._filtered_jobs: List[Job] = []
        self._scored_jobs: List[Job] = []
        self._skill_match_ratios: Dict[int, float] = {}
        self._generated_proposals: Dict[int, str] = {}
        self._notified_job_match_ids: set[int] = set()
        self._notified_manual_apply_ids: set[int] = set()
        self._auto_applied_count = 0
        self._manual_apply_count = 0

    def check_for_new_jobs(self) -> int:
        """Run a lightweight fetch pass and return newly discovered job count.

        This method fetches jobs from all enabled platforms, persists only new
        records (deduped by job URL), and caches newly inserted job IDs to be
        consumed by the next full pipeline run.
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
                    message=f"Fetched {saved_count} jobs from {fetcher.platform.title()}",
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
            Job.objects.filter(created_at__gte=run_started_at)
            .order_by("-created_at")
        )
        self._new_job_ids_from_check = [job.id for job in discovered_jobs]

        logger.info(
            "Lightweight job check completed | saved=%d discovered=%d",
            total_saved,
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
        """Run the full job automation workflow in stage order.

        Args:
            user_id: User identifier for skill matching, proposal generation,
                and job applications.
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
            self._run_stage("filter_jobs", self.filter_jobs, user_id)
            self._run_stage("score_jobs", self.score_jobs)
            self._run_stage("generate_proposals", self.generate_proposals, user_id)
            self._run_stage("apply_to_jobs", self.apply_to_jobs, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline execution failed for user_id=%s", user_id)
            self._notify_error(str(exc))
            raise
        finally:
            self._notify_daily_summary()
            # Consume lightweight-check discoveries so each batch is processed once.
            self._new_job_ids_from_check = []

        logger.info(
            "Pipeline finished for user_id=%s | fetched=%d filtered=%d scored=%d proposals=%d auto_applied=%d manual_apply=%d",
            user_id,
            len(self._fetched_jobs),
            len(self._filtered_jobs),
            len(self._scored_jobs),
            len(self._generated_proposals),
            self._auto_applied_count,
            self._manual_apply_count,
        )
        log_event(
            level="INFO",
            module="scheduler",
            action="pipeline_finish",
            message=(
                f"Pipeline finished for user_id={user_id} "
                f"(fetched={len(self._fetched_jobs)}, filtered={len(self._filtered_jobs)}, "
                f"scored={len(self._scored_jobs)}, proposals={len(self._generated_proposals)}, "
                f"auto_applied={self._auto_applied_count}, manual_apply={self._manual_apply_count})"
            ),
            status="SUCCESS",
        )

    def fetch_jobs(self) -> None:
        """Load jobs inserted during the lightweight check stage."""

        logger.info("Stage fetch_jobs started")

        fetched_qs: QuerySet[Job] = Job.objects.filter(
            id__in=self._new_job_ids_from_check
        ).order_by("-created_at")
        self._fetched_jobs = list(fetched_qs)

        logger.info(
            "Stage fetch_jobs completed | fetched_jobs=%d",
            len(self._fetched_jobs),
        )

    def filter_jobs(self, user_id: int) -> None:
        """Filter out jobs with zero skill matches for the target user.

        Args:
            user_id: User identifier used to fetch skill inventory.
        """

        logger.info("Stage filter_jobs started")

        user_skills = self._skill_matcher.get_user_skills(user_id)
        if not user_skills:
            logger.warning("No user skills found for user_id=%s; all jobs filtered out.", user_id)
            self._filtered_jobs = []
            return

        filtered: List[Job] = []
        match_ratios: Dict[int, float] = {}
        for job in self._fetched_jobs:
            match_result = self._skill_matcher.match_job_skills(
                job_title=job.title,
                job_description=job.description,
                user_skills=user_skills,
            )
            if int(match_result.get("match_count", 0)) > 0:
                filtered.append(job)
                match_ratios[job.id] = float(match_result.get("match_ratio", 0.0))

        self._filtered_jobs = filtered
        self._skill_match_ratios = match_ratios

        logger.info(
            "Stage filter_jobs completed | input=%d kept=%d removed=%d",
            len(self._fetched_jobs),
            len(self._filtered_jobs),
            max(len(self._fetched_jobs) - len(self._filtered_jobs), 0),
        )

    def score_jobs(self) -> None:
        """Classify and score filtered jobs, then persist score/category fields."""

        logger.info("Stage score_jobs started")

        scored: List[Job] = []
        for job in self._filtered_jobs:
            hourly_rate = float(job.hourly_rate or 0.0)
            budget = float(job.budget or 0.0)

            category = self._classifier.classify_job(
                job_title=job.title,
                job_description=job.description,
                hourly_rate=hourly_rate,
            )

            match_ratio = self._skill_match_ratios.get(job.id, 0.0)

            score = self._scorer.calculate_job_score(
                skill_match_ratio=match_ratio,
                category=category,
                budget=budget,
                hourly_rate=hourly_rate,
            )

            job.category = category
            job.score = score
            job.save(update_fields=["category", "score"])
            scored.append(job)

            if self._scorer.should_apply(score) and not job.applications.exists():
                self._notify_high_quality_job(job=job, score=score)

        self._scored_jobs = scored

        logger.info("Stage score_jobs completed | scored_jobs=%d", len(self._scored_jobs))

    def generate_proposals(self, user_id: int) -> None:
        """Generate optimized proposal text for jobs above apply threshold.

        Generated proposals are stored temporarily in-memory for the current run
        and keyed by job id.

        Args:
            user_id: User identifier used to load context and templates.
        """

        logger.info("Stage generate_proposals started")

        if self._proposal_generator is None:
            try:
                self._proposal_generator = ProposalGenerator()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "ProposalGenerator initialization failed; skipping proposal stage."
                )
                self._generated_proposals = {}
                return

        user_context = self._proposal_builder.get_user_context(user_id)
        generated: Dict[int, str] = {}

        for job in self._scored_jobs:
            if not self._scorer.should_apply(job.score):
                continue

            try:
                job_context = self._proposal_builder.build_job_context(job)
                proposal_input = self._proposal_builder.build_proposal_input(
                    user_context=user_context,
                    job_context=job_context,
                )

                proposal = self._proposal_generator.generate_proposal(
                    user_context=proposal_input["user_context"],
                    job_context=proposal_input["job_context"],
                )
                proposal = self._proposal_optimizer.optimize_proposal(proposal)
                generated[job.id] = proposal
            except Exception:  # noqa: BLE001
                logger.exception("Proposal generation failed for job_id=%s", job.id)
                log_event(
                    level="ERROR",
                    module="proposal_generator",
                    action="generate_proposal",
                    platform=job.platform,
                    job_url=job.job_url,
                    message=f"Proposal generation failed for job_id={job.id}",
                    status="FAILED",
                    stack_trace=traceback.format_exc(),
                )

        self._generated_proposals = generated

        logger.info(
            "Stage generate_proposals completed | generated=%d",
            len(self._generated_proposals),
        )

    def apply_to_jobs(self, user_id: int) -> None:
        """Submit applications for proposal-ready jobs via apply engine.

        Args:
            user_id: User identifier associated with each application.
        """

        logger.info("Stage apply_to_jobs started")

        applications_today = self._applications_count_today(user_id)
        remaining_quota = max(MAX_APPLICATIONS_PER_DAY - applications_today, 0)

        if remaining_quota <= 0:
            logger.info(
                "Daily apply quota reached for user_id=%s (%d/%d)",
                user_id,
                applications_today,
                MAX_APPLICATIONS_PER_DAY,
            )
            return

        applied_success = 0
        for job in self._scored_jobs:
            if remaining_quota <= 0:
                break
            if job.id not in self._generated_proposals:
                continue

            proposal_text = self._generated_proposals[job.id]
            success = self._apply_engine.apply_to_job(
                user_id=user_id,
                job=job,
                proposal_text=proposal_text,
                score=float(job.score),
            )
            if success:
                applied_success += 1
                self._auto_applied_count += 1
                remaining_quota -= 1
            else:
                self._manual_apply_count += 1
                self._notify_manual_apply_required(job=job, score=float(job.score))

        logger.info(
            "Stage apply_to_jobs completed | successful=%d remaining_quota=%d",
            applied_success,
            remaining_quota,
        )

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
        self._skill_match_ratios = {}
        self._generated_proposals = {}
        self._auto_applied_count = 0
        self._manual_apply_count = 0

    @staticmethod
    def _applications_count_today(user_id: int) -> int:
        """Return number of application records created today for a user."""

        today = date.today()
        return Application.objects.filter(user_id=user_id, applied_at__date=today).count()

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

        self._send_notification(
            lambda notifier: notifier.send_daily_summary(
                jobs_scanned=len(self._fetched_jobs),
                relevant_jobs=len(self._filtered_jobs),
                auto_applied=self._auto_applied_count,
                manual_apply=self._manual_apply_count,
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
