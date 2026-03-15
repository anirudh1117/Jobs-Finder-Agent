"""RemoteOK application automation handler."""

from __future__ import annotations

import logging
from typing import Iterable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from core.auto_apply.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

_FORM_TEXTAREA_SELECTORS: tuple[str, ...] = (
    "textarea[name='cover_letter']",
    "textarea[name='message']",
    "textarea[aria-label*='cover' i]",
    "textarea[aria-label*='message' i]",
)

_FORM_SUBMIT_SELECTORS: tuple[str, ...] = (
    "button[type='submit']",
    "button:has-text('Apply')",
    "button:has-text('Submit')",
)

_EXTERNAL_LINK_SELECTORS: tuple[str, ...] = (
    "a:has-text('Apply externally')",
    "a:has-text('External apply')",
    "a[href*='greenhouse.io']",
    "a[href*='lever.co']",
)


class RemoteOKApplyHandler:
    """Handles RemoteOK apply flows with form-or-external-link fallback."""

    def __init__(self, browser_manager: BrowserManager) -> None:
        """Store shared browser manager for realistic interaction delays."""

        self._browser_manager = browser_manager

    def apply(self, page: Page, job_url: str, proposal_text: str) -> bool:
        """Apply via form when present, otherwise return False for manual apply.

        Args:
            page: Active Playwright page.
            job_url: RemoteOK job URL.
            proposal_text: Proposal text to fill in form fields.

        Returns:
            True when an on-page form submission appears successful.
            False when only an external link exists or submission fails.
        """

        try:
            page.goto(job_url, wait_until="domcontentloaded")
            self._browser_manager.simulate_human_delay(1.0, 2.0)

            if _first_existing_selector(page, _EXTERNAL_LINK_SELECTORS) is not None:
                logger.info("RemoteOK job requires external apply: %s", job_url)
                return False

            textarea_selector = _first_existing_selector(page, _FORM_TEXTAREA_SELECTORS)
            submit_selector = _first_existing_selector(page, _FORM_SUBMIT_SELECTORS)

            if textarea_selector is None or submit_selector is None:
                logger.info("RemoteOK in-page application form not found: %s", job_url)
                return False

            page.fill(textarea_selector, proposal_text)
            self._browser_manager.simulate_human_delay(0.8, 1.5)

            page.click(submit_selector)
            self._browser_manager.simulate_human_delay(1.0, 2.0)

            success_indicators = [
                "text=Application sent",
                "text=Thanks for applying",
                "text=Successfully submitted",
            ]
            return any(page.locator(sel).count() > 0 for sel in success_indicators)
        except PlaywrightTimeoutError:
            logger.warning("Timeout during RemoteOK apply flow for %s", job_url)
            return False
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected RemoteOK apply failure for %s", job_url)
            return False


def _first_existing_selector(page: Page, selectors: Iterable[str]) -> str | None:
    """Return first selector that resolves to one or more nodes."""

    for selector in selectors:
        if page.locator(selector).count() > 0:
            return selector
    return None
