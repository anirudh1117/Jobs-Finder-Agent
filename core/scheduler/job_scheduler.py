"""Periodic scheduler for running the job automation pipeline."""

from __future__ import annotations

import logging
import time

from core.config.constants import JOB_FETCH_INTERVAL_HOURS
from core.scheduler.job_pipeline import JobPipeline

logger = logging.getLogger(__name__)


class JobScheduler:
    """Runs a two-stage loop: lightweight detection, then conditional full pipeline.

    The scheduler checks for newly discovered jobs on a fixed cadence. Heavy
    processing is only executed when new jobs were found in that cycle.
    """

    def __init__(self, pipeline: JobPipeline | None = None) -> None:
        """Initialize scheduler with an optional injected pipeline."""

        self._pipeline = pipeline or JobPipeline()
        self._running = False

    def start_scheduler(self, user_id: int) -> None:
        """Start periodic two-stage execution for the target user.

        This method blocks in a loop until ``stop_scheduler`` is called.

        Args:
            user_id: User identifier passed through to pipeline execution.
        """

        self._running = True
        interval_seconds = max(int(JOB_FETCH_INTERVAL_HOURS * 3600), 1)

        logger.info(
            "JobScheduler started | user_id=%s interval_seconds=%d",
            user_id,
            interval_seconds,
        )

        while self._running:
            try:
                new_jobs = self._pipeline.check_for_new_jobs()

                if new_jobs > 0:
                    logger.info("%d new jobs detected. Running full pipeline.", new_jobs)
                    self._pipeline.run_pipeline(user_id=user_id)
                else:
                    logger.info("No new jobs detected. Skipping pipeline.")
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Scheduler loop iteration failed unexpectedly; continuing."
                )

            slept = 0
            while self._running and slept < interval_seconds:
                time.sleep(1)
                slept += 1

        logger.info("JobScheduler stopped | user_id=%s", user_id)

    def stop_scheduler(self) -> None:
        """Request safe scheduler termination."""

        self._running = False
