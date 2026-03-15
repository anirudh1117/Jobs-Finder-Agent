"""Extracts raw text from PDF resume files using pypdf."""

from __future__ import annotations

import logging
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)


class ResumeParser:
    """Reads a PDF resume and returns cleaned plain text.

    Delegates all PDF I/O to pypdf so that the rest of the system handles
    only plain strings, not binary file data.
    """

    def extract_text(self, file_path: str) -> str:
        """Open a PDF resume and extract all text from every page.

        Args:
            file_path: Absolute or relative path to the PDF file.

        Returns:
            A single cleaned string containing the concatenated text of all
            pages in reading order.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the PDF is encrypted, corrupted, or contains no
                        extractable text.
        """

        try:
            reader = PdfReader(file_path)
        except FileNotFoundError:
            raise
        except PdfReadError as exc:
            raise ValueError(
                f"Could not read PDF file '{file_path}': {exc}"
            ) from exc

        if reader.is_encrypted:
            raise ValueError(
                f"The PDF file '{file_path}' is encrypted and cannot be parsed."
            )

        page_texts: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
                page_texts.append(raw)
            except Exception as exc:  # noqa: BLE001 – best-effort per page
                logger.warning(
                    "Could not extract text from page %d of '%s': %s",
                    page_number,
                    file_path,
                    exc,
                )

        combined = "\n".join(page_texts)
        cleaned = self._clean_text(combined)

        if not cleaned.strip():
            raise ValueError(
                f"No extractable text found in '{file_path}'. "
                "The PDF may contain only scanned images."
            )

        return cleaned

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(raw: str) -> str:
        """Normalise whitespace in extracted PDF text.

        Args:
            raw: The raw concatenated text from all PDF pages.

        Returns:
            Text with consecutive blank lines collapsed to a single blank line
            and leading/trailing whitespace removed from each line.
        """

        # Strip trailing whitespace from every line.
        lines = [line.rstrip() for line in raw.splitlines()]

        # Replace runs of 3+ consecutive newlines with two newlines.
        joined = "\n".join(lines)
        joined = re.sub(r"\n{3,}", "\n\n", joined)

        return joined.strip()
