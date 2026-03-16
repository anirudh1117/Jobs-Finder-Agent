"""Platform-agnostic orchestration engine for automatic job applications."""

from __future__ import annotations

import logging
import traceback

from core.auto_apply.browser_manager import BrowserManager
from core.auto_apply.platform_apply_handlers.linkedin_apply import LinkedInApplyHandler
from core.auto_apply.platform_apply_handlers.remoteok_apply import RemoteOKApplyHandler
from core.auto_apply.platform_apply_handlers.upwork_apply import UpworkApplyHandler
from core.config.constants import LINKEDIN, REMOTEOK, UPWORK
from core.database.db_manager import DatabaseManager
from core.database.models import Application, Job, User
from core.logging.system_logger import log_event
from core.notifications.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class ApplyEngine:
    """Coordinates browser automation and records application outcomes."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        browser_manager: BrowserManager | None = None,
    ) -> None:
        """Initialize the apply engine with injectable dependencies."""

        self._db = db_manager or DatabaseManager()
        self._browser_manager = browser_manager or BrowserManager()
        self._notifier = self._initialize_notifier()

    def get_handler(self, platform: str):
        """Return a platform-specific application handler instance.

        Args:
            platform: Normalized platform identifier.

        Returns:
            A handler instance for the matching platform.

        Raises:
            ValueError: If the platform is unsupported.
        """

        normalized = platform.strip().lower()
        if normalized == UPWORK:
            return UpworkApplyHandler(self._browser_manager)
        if normalized == LINKEDIN:
            return LinkedInApplyHandler(self._browser_manager)
        if normalized == REMOTEOK:
            return RemoteOKApplyHandler(self._browser_manager)

        raise ValueError(f"Unsupported auto-apply platform: {platform}")

    def apply_to_job(
        self,
        user_id: int,
        job: Job,
        proposal_text: str,
        score: float | None = None,
    ) -> bool:
        """Run auto-apply flow and persist the result.

        Args:
            user_id: User id to associate with the application attempt.
            job: The job object to apply to.
            proposal_text: Pre-generated proposal text to submit.
            score: Optional job relevance score for notifications.

        Returns:
            True when submission appears successful, otherwise False.
        """

        user = User.objects.get(pk=user_id)
        success = False

        log_event(
            level="INFO",
            module="auto_apply",
            action="apply_to_job",
            platform=job.platform,
            job_url=job.job_url,
            message=f"Starting auto-apply for job_id={job.id}",
            status="SUCCESS",
        )

        try:
            handler = self.get_handler(job.platform)
            self._browser_manager.start_browser()
            page = self._browser_manager.get_page()

            success = handler.apply(page=page, job_url=job.job_url, proposal_text=proposal_text)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Auto-apply failed | user_id=%s job_id=%s platform=%s",
                user_id,
                job.id,
                job.platform,
            )
            log_event(
                level="ERROR",
                module="auto_apply",
                action="apply_to_job",
                platform=job.platform,
                job_url=job.job_url,
                message=f"Auto-apply failed for job_id={job.id}",
                status="FAILED",
                stack_trace=traceback.format_exc(),
            )
            success = False
        finally:
            self._browser_manager.close_browser()

        self._record_application_result(
            user=user,
            job=job,
            proposal_text=proposal_text,
            success=success,
        )

        if success and score is not None:
            self._send_auto_apply_notification(job=job, score=score)

        log_event(
            level="INFO" if success else "WARNING",
            module="auto_apply",
            action="apply_to_job",
            platform=job.platform,
            job_url=job.job_url,
            message=(
                f"Auto-apply succeeded for job_id={job.id}"
                if success
                else f"Auto-apply did not complete for job_id={job.id}"
            ),
            status="SUCCESS" if success else "FAILED",
        )

        return success

    def _record_application_result(
        self,
        user: User,
        job: Job,
        proposal_text: str,
        success: bool,
    ) -> None:
        """Persist application record with status derived from outcome."""

        application = self._db.save_application(
            user=user,
            job=job,
            proposal_text=proposal_text,
        )

        if not success:
            application.status = Application.Status.REJECTED
            application.save(update_fields=["status"])

    @staticmethod
    def _initialize_notifier() -> TelegramNotifier | None:
        """Create a Telegram notifier when configuration is available."""

        try:
            return TelegramNotifier()
        except ValueError as exc:
            logger.warning(
                "Telegram notifier unavailable in ApplyEngine; notifications disabled. %s",
                exc,
            )
            return None
        except Exception:
            logger.exception(
                "Telegram notifier initialization failed unexpectedly in ApplyEngine."
            )
            return None

    def _send_auto_apply_notification(self, job: Job, score: float) -> None:
        """Send best-effort Telegram alert after a successful auto-application."""

        if self._notifier is None:
            return

        try:
            sent = self._notifier.send_auto_apply_notification(job=job, score=score)
            if not sent:
                logger.warning("Auto-apply Telegram notification was not sent for job_id=%s", job.id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send auto-apply Telegram notification for job_id=%s", job.id)
