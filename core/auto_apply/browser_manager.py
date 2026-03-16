"""Reusable Playwright browser lifecycle manager."""

from __future__ import annotations

import logging
import random
import time
import traceback

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from core.config.settings import PLAYWRIGHT_HEADLESS, PLAYWRIGHT_TIMEOUT
from core.logging.system_logger import log_event

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages Playwright startup, page creation, delays, and shutdown."""

    def __init__(self) -> None:
        """Initialize internal Playwright state holders."""

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def start_browser(self) -> None:
        """Start Playwright and launch a Chromium browser instance.

        Raises:
            RuntimeError: If browser startup fails.
        """

        if self._browser is not None:
            return

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
            log_event(
                level="INFO",
                module="auto_apply",
                action="browser_start",
                message="Playwright browser started",
                status="SUCCESS",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to start Playwright browser.")
            log_event(
                level="ERROR",
                module="auto_apply",
                action="browser_start",
                message="Failed to start Playwright browser",
                status="FAILED",
                stack_trace=traceback.format_exc(),
            )
            self.close_browser()
            raise RuntimeError("Could not start Playwright browser.") from exc

    def get_page(self) -> Page:
        """Create and return a new page instance from the active browser.

        Returns:
            A Playwright Page object.

        Raises:
            RuntimeError: If browser is not started.
        """

        if self._browser is None:
            raise RuntimeError("Browser has not been started. Call start_browser() first.")

        context = self._browser.new_context()
        page = context.new_page()
        page.set_default_timeout(PLAYWRIGHT_TIMEOUT)
        return page

    def close_browser(self) -> None:
        """Safely close browser and Playwright session."""

        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                logger.exception("Error while closing browser.")
                log_event(
                    level="ERROR",
                    module="auto_apply",
                    action="browser_close",
                    message="Error while closing browser",
                    status="FAILED",
                    stack_trace=traceback.format_exc(),
                )
            finally:
                self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Error while stopping Playwright.")
                log_event(
                    level="ERROR",
                    module="auto_apply",
                    action="browser_stop",
                    message="Error while stopping Playwright",
                    status="FAILED",
                    stack_trace=traceback.format_exc(),
                )
            finally:
                self._playwright = None

    @staticmethod
    def simulate_human_delay(min_seconds: float, max_seconds: float) -> None:
        """Sleep for a random duration to mimic human interaction timing.

        Args:
            min_seconds: Minimum delay in seconds.
            max_seconds: Maximum delay in seconds.
        """

        if min_seconds < 0 or max_seconds < 0:
            return
        lower = min(min_seconds, max_seconds)
        upper = max(min_seconds, max_seconds)
        time.sleep(random.uniform(lower, upper))
