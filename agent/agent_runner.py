"""Main lifecycle controller for the Freelance Agent system."""

from __future__ import annotations

import logging

from core.config.constants import DEFAULT_USER_ID, JOB_FETCH_INTERVAL_HOURS
from core.config import settings as app_settings
from core.notifications.telegram_notifier import TelegramNotifier
from core.scheduler.job_pipeline import JobPipeline
from core.scheduler.job_scheduler import JobScheduler

logger = logging.getLogger(__name__)


class FreelanceAgentRunner:
    """Coordinate agent startup, one-shot execution, and graceful shutdown.

    This class is the main controller of the system. It does not implement
    business logic itself; it delegates recurring execution to ``JobScheduler``
    and direct one-off runs to ``JobPipeline``.
    """

    def __init__(self, user_id: int) -> None:
        """Initialize core services and prepare runner state.

        Args:
            user_id: User identifier used by the scheduler and pipeline.
        """

        self.user_id = user_id
        self._pipeline = JobPipeline()
        self._scheduler = JobScheduler(pipeline=self._pipeline)
        self._notifier = self._initialize_notifier()
        self._is_running = False

        logger.info(
            "FreelanceAgentRunner initialized | user_id=%s telegram_enabled=%s telegram_config_present=%s",
            self.user_id,
            self._notifier is not None,
            bool(app_settings.TELEGRAM_BOT_TOKEN and app_settings.TELEGRAM_CHAT_ID),
        )

    def start(self) -> None:
        """Start the agent scheduler and send a startup notification.

        Startup errors are logged and re-raised so they do not fail silently.
        """

        logger.info("Agent starting | user_id=%s", self.user_id)

        try:
            self._is_running = True
            self._notify(
                "🚀 Freelance Agent Started\n\nAutomation pipeline is now running."
            )

            logger.info(
                "Scheduler starting | user_id=%s interval_hours=%s",
                self.user_id,
                JOB_FETCH_INTERVAL_HOURS,
            )
            self._scheduler.start_scheduler(user_id=self.user_id)
        except Exception:
            self._is_running = False
            logger.exception("Agent startup failed | user_id=%s", self.user_id)
            self._notify(
                "❗ Freelance Agent Error\n\nAgent startup failed. Check application logs for details."
            )
            raise

    def stop(self) -> None:
        """Stop the scheduler and send a shutdown notification."""

        logger.info("Agent stopping | user_id=%s", self.user_id)
        self._scheduler.stop_scheduler()
        self._is_running = False
        self._notify(
            "🛑 Freelance Agent Stopped\n\nAutomation pipeline has been stopped."
        )
        logger.info("Agent stopped | user_id=%s", self.user_id)

    def run_once(self) -> None:
        """Execute the pipeline once without starting the recurring scheduler.

        Useful for testing, manual execution, and debugging.
        """

        logger.info("Pipeline executing once | user_id=%s", self.user_id)
        try:
            self._pipeline.run_pipeline(user_id=self.user_id)
            logger.info("Pipeline executed | user_id=%s", self.user_id)
        except Exception:
            logger.exception("One-shot pipeline execution failed | user_id=%s", self.user_id)
            self._notify(
                "❗ Freelance Agent Error\n\nOne-time pipeline execution failed. Check application logs for details."
            )
            raise

    @staticmethod
    def _initialize_notifier() -> TelegramNotifier | None:
        """Initialize Telegram notifier if configuration is available.

        Returns:
            TelegramNotifier instance when configuration is valid, otherwise None.
        """

        try:
            return TelegramNotifier()
        except ValueError as exc:
            logger.warning(
                "Telegram notifier is unavailable; startup/shutdown notifications are disabled. %s",
                exc,
            )
            return None
        except Exception:
            logger.exception(
                "Telegram notifier initialization failed unexpectedly; notifications are disabled."
            )
            return None

    def _notify(self, message: str) -> None:
        """Send a best-effort Telegram notification when notifier is enabled."""

        if self._notifier is None:
            return

        try:
            self._notifier.send_message(message)
        except Exception:
            logger.exception("Failed to send agent lifecycle notification.")


def main() -> None:
    """Run the Freelance Agent using the default user identifier.

    Example:
        python agent_runner.py
    """

    runner = FreelanceAgentRunner(user_id=DEFAULT_USER_ID)

    try:
        runner.start()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; stopping agent.")
        runner.stop()


if __name__ == "__main__":
    main()