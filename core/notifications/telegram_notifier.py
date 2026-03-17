"""Telegram notification sender using the Telegram Bot HTTP API."""

from __future__ import annotations

import logging
from typing import Any

import requests

from core.config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send plain-text notifications to Telegram via Bot HTTP API.

    Supports both global notifications (to a configured default chat ID)
    and per-user notifications (to specific chat IDs from user profiles).
    """

    def __init__(self) -> None:
        """Load Telegram configuration and build sendMessage endpoint.

        Note: TELEGRAM_CHAT_ID is now optional. If not provided, only
        per-user notifications (with explicit chat_id) can be sent.
        """

        self._bot_token = TELEGRAM_BOT_TOKEN
        self._chat_id = TELEGRAM_CHAT_ID

        if not self._bot_token:
            raise ValueError(
                "Missing TELEGRAM_BOT_TOKEN. Set it in environment variables."
            )

        self._api_url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"

    def send_message(self, message: str, chat_id: str | None = None) -> bool:
        """Send a plain-text message to a Telegram chat.

        Args:
            message: Message content to send.
            chat_id: Optional Telegram chat ID. If not provided, uses the default
                    TELEGRAM_CHAT_ID from environment. If neither is available, returns False.

        Returns:
            True if Telegram accepted the message, otherwise False.
        """

        target_chat_id = chat_id or self._chat_id
        if not target_chat_id:
            logger.warning(
                "No chat_id provided and TELEGRAM_CHAT_ID not configured. "
                "Cannot send message."
            )
            return False

        payload = {
            "chat_id": target_chat_id,
            "text": message,
        }

        try:
            response = requests.post(self._api_url, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            logger.exception("Failed to send Telegram message due to network/API error.")
            return False
        except ValueError:
            logger.exception("Failed to decode Telegram API response JSON.")
            return False

        if not bool(data.get("ok")):
            logger.error("Telegram API rejected message: %s", data)
            return False

        logger.debug(f"Telegram message sent to chat {target_chat_id}")
        return True

    def send_job_match_notification(
        self, job: Any, score: float, chat_id: str | None = None
    ) -> bool:
        """Send notification for a high-quality job match.

        Args:
            job: Job object with platform, title, budget, and job_url fields.
            score: Computed relevance score.
            chat_id: Optional Telegram chat ID for per-user notification.

        Returns:
            True when message is sent successfully.
        """

        message = (
            "🔥 New Job Match\n\n"
            f"Platform: {self._safe_attr(job, 'platform')}\n"
            f"Title: {self._safe_attr(job, 'title')}\n"
            f"Budget: {self._format_budget(self._safe_attr(job, 'budget'))}\n"
            f"Score: {score:.2f}\n\n"
            "Status: NOT APPLIED\n\n"
            "Job Link:\n"
            f"{self._safe_attr(job, 'job_url')}"
        )
        return self.send_message(message, chat_id=chat_id)

    def send_auto_apply_notification(
        self, job: Any, score: float, chat_id: str | None = None
    ) -> bool:
        """Send notification when a job is successfully auto-applied.

        Args:
            job: Job object with platform, title, budget, and job_url fields.
            score: Computed relevance score.
            chat_id: Optional Telegram chat ID for per-user notification.

        Returns:
            True when message is sent successfully.
        """

        message = (
            "🚀 Job Applied\n\n"
            f"Platform: {self._safe_attr(job, 'platform')}\n"
            f"Title: {self._safe_attr(job, 'title')}\n"
            f"Budget: {self._format_budget(self._safe_attr(job, 'budget'))}\n"
            f"Score: {score:.2f}\n\n"
            "Status: AUTO APPLIED\n\n"
            "Job Link:\n"
            f"{self._safe_attr(job, 'job_url')}"
        )
        return self.send_message(message, chat_id=chat_id)

    def send_manual_apply_notification(
        self, job: Any, score: float, chat_id: str | None = None
    ) -> bool:
        """Send notification when manual application is required.

        Args:
            job: Job object with platform, title, budget, and job_url fields.
            score: Computed relevance score.
            chat_id: Optional Telegram chat ID for per-user notification.

        Returns:
            True when message is sent successfully.
        """

        message = (
            "⚠️ Manual Application Required\n\n"
            f"Platform: {self._safe_attr(job, 'platform')}\n"
            f"Title: {self._safe_attr(job, 'title')}\n"
            f"Budget: {self._format_budget(self._safe_attr(job, 'budget'))}\n"
            f"Score: {score:.2f}\n\n"
            "Status: MANUAL APPLY REQUIRED\n\n"
            "Job Link:\n"
            f"{self._safe_attr(job, 'job_url')}"
        )
        return self.send_message(message, chat_id=chat_id)

    def send_daily_summary(
        self,
        jobs_scanned: int,
        relevant_jobs: int,
        auto_applied: int,
        manual_apply: int,
        chat_id: str | None = None,
    ) -> bool:
        """Send a daily summary report for pipeline activity.

        Args:
            jobs_scanned: Total jobs processed by the pipeline.
            relevant_jobs: Jobs that passed filtering/scoring criteria.
            auto_applied: Jobs successfully auto-applied.
            manual_apply: Jobs requiring manual application.
            chat_id: Optional Telegram chat ID for per-user notification.

        Returns:
            True when message is sent successfully.
        """

        message = (
            "📊 Daily Freelance Agent Report\n\n"
            f"Jobs scanned: {jobs_scanned}\n"
            f"Relevant jobs: {relevant_jobs}\n"
            f"Applications sent: {auto_applied}\n"
            f"Manual apply jobs: {manual_apply}"
        )
        return self.send_message(message, chat_id=chat_id)

    def send_error_notification(
        self, error_message: str, chat_id: str | None = None
    ) -> bool:
        """Send a critical pipeline error notification.

        Args:
            error_message: Human-readable error details.
            chat_id: Optional Telegram chat ID for per-user notification.

        Returns:
            True when message is sent successfully.
        """

        message = f"❗ Freelance Agent Error\n\n{error_message}"
        return self.send_message(message, chat_id=chat_id)

    @staticmethod
    def _safe_attr(obj: Any, attr_name: str) -> str:
        """Safely get an attribute from an object and convert it to string."""

        value = getattr(obj, attr_name, "")
        return str(value) if value is not None else ""

    @staticmethod
    def _format_budget(value: Any) -> str:
        """Format numeric budget values consistently for notifications."""

        try:
            if value in (None, ""):
                return "N/A"
            amount = float(value)
            return f"${amount:.2f}"
        except (TypeError, ValueError):
            return str(value) if value else "N/A"
