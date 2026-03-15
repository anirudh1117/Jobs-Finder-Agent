"""LinkedIn Easy Apply automation handler."""

from __future__ import annotations

import logging
from typing import Iterable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from core.auto_apply.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

_EASY_APPLY_SELECTORS: tuple[str, ...] = (
    "button:has-text('Easy Apply')",
    "button[aria-label*='Easy Apply' i]",
)

_MESSAGE_SELECTORS: tuple[str, ...] = (
    "textarea[name='message']",
    "textarea[aria-label*='message' i]",
    "textarea[id*='message']",
)

_SUBMIT_SELECTORS: tuple[str, ...] = (
    "button:has-text('Submit application')",
    "button[aria-label*='Submit application' i]",
    "button:has-text('Review')",
)


class LinkedInApplyHandler:
    """Handles LinkedIn Easy Apply interactions when publicly accessible."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        """Store shared browser manager for human-like pacing."""

        self._browser_manager = browser_manager

    def apply(self, page: Page, job_url: str, proposal_text: str) -> bool:
        """Attempt to submit a LinkedIn Easy Apply application.

        Args:
            page: Active Playwright page.
            job_url: LinkedIn job URL.
            proposal_text: Proposal text inserted into message field when present.

        Returns:
            True if submission appears successful, otherwise False.
        """

        try:
            page.goto(job_url, wait_until="domcontentloaded")
            self._browser_manager.simulate_human_delay(1.0, 2.0)

            easy_apply = _first_existing_selector(page, _EASY_APPLY_SELECTORS)
            if easy_apply is None:
                logger.info("LinkedIn Easy Apply button not found: %s", job_url)
                return False

            page.click(easy_apply)
            self._browser_manager.simulate_human_delay(1.0, 1.8)

            message_selector = _first_existing_selector(page, _MESSAGE_SELECTORS)
            if message_selector is not None:
                page.fill(message_selector, proposal_text)
                self._browser_manager.simulate_human_delay(0.8, 1.4)

            submit_selector = _first_existing_selector(page, _SUBMIT_SELECTORS)
            if submit_selector is None:
                logger.warning("LinkedIn submit/review button not found: %s", job_url)
                return False

            page.click(submit_selector)
            self._browser_manager.simulate_human_delay(1.0, 2.0)

            success_indicators = [
                "text=Application submitted",
                "text=Your application was sent",
                "text=Done",
            ]
            return any(page.locator(sel).count() > 0 for sel in success_indicators)
        except PlaywrightTimeoutError:
            logger.warning("Timeout during LinkedIn apply flow for %s", job_url)
            return False
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected LinkedIn apply failure for %s", job_url)
            return False


def _first_existing_selector(page: Page, selectors: Iterable[str]) -> str | None:
    """Return first selector that resolves to one or more nodes."""

    for selector in selectors:
        if page.locator(selector).count() > 0:
            return selector
    return None
