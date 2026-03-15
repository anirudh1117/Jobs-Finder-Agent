"""Upwork-specific browser automation for job applications."""

from __future__ import annotations

import logging
from typing import Iterable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from core.auto_apply.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

# Keep selectors explicit and easy to update.
_UPWORK_PROPOSAL_SELECTORS: tuple[str, ...] = (
    "textarea[name='coverLetter']",
    "textarea[data-test='cover-letter']",
    "textarea[aria-label*='cover letter' i]",
)

_UPWORK_SUBMIT_SELECTORS: tuple[str, ...] = (
    "button[data-test='submit-proposal']",
    "button:has-text('Submit')",
    "button:has-text('Send')",
)


class UpworkApplyHandler:
    """Handles Upwork application submission workflow."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        """Store shared browser manager for human-like delays."""

        self._browser_manager = browser_manager

    def apply(self, page: Page, job_url: str, proposal_text: str) -> bool:
        """Attempt to submit an Upwork proposal.

        Args:
            page: Active Playwright page.
            job_url: Upwork job URL.
            proposal_text: Proposal content to insert.

        Returns:
            True if submission appears successful, otherwise False.
        """

        try:
            page.goto(job_url, wait_until="domcontentloaded")
            self._browser_manager.simulate_human_delay(1.0, 2.0)

            proposal_selector = _first_visible_selector(page, _UPWORK_PROPOSAL_SELECTORS)
            if proposal_selector is None:
                logger.warning("Upwork proposal textarea not found: %s", job_url)
                return False

            page.fill(proposal_selector, proposal_text)
            self._browser_manager.simulate_human_delay(0.8, 1.6)

            submit_selector = _first_visible_selector(page, _UPWORK_SUBMIT_SELECTORS)
            if submit_selector is None:
                logger.warning("Upwork submit button not found: %s", job_url)
                return False

            page.click(submit_selector)
            self._browser_manager.simulate_human_delay(1.2, 2.2)

            # Heuristic success checks.
            success_indicators = [
                "text=Application submitted",
                "text=Proposal submitted",
                "text=Thanks for applying",
            ]
            return any(page.locator(sel).count() > 0 for sel in success_indicators)
        except PlaywrightTimeoutError:
            logger.warning("Timeout during Upwork apply flow for %s", job_url)
            return False
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected Upwork apply failure for %s", job_url)
            return False


def _first_visible_selector(page: Page, selectors: Iterable[str]) -> str | None:
    """Return first selector that resolves to at least one visible element."""

    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0 and locator.first.is_visible():
            return selector
    return None
