"""Classifies job postings into normalised category constants."""

from __future__ import annotations

from typing import List

from core.config.constants import (
    CATEGORY_AI_TRAINING,
    CATEGORY_OTHER,
    CATEGORY_SOFTWARE_DEV,
    MIN_AI_TRAINING_RATE,
)
from core.job_filter.skill_matcher import normalize_text

# Keywords that indicate an AI training / data-labelling job.
_AI_TRAINING_KEYWORDS: List[str] = [
    "ai training",
    "prompt evaluation",
    "model evaluation",
    "ai reviewer",
    "ai trainer",
    "llm training",
    "annotation",
    "data labeling",
    "data labelling",
    "prompt engineering",
]

# Keywords that indicate a software / web development job.
_SOFTWARE_DEV_KEYWORDS: List[str] = [
    "python",
    "django",
    "react",
    "javascript",
    "backend",
    "api",
    "full stack",
    "fullstack",
    "web development",
]


def contains_keywords(text: str, keywords: List[str]) -> bool:
    """Return True if any keyword from *keywords* is found in *text*.

    Both the text and each keyword are compared after normalisation so that
    casing and extra whitespace do not affect the result.

    Args:
        text: The pre-normalised (lowercase, collapsed whitespace) job text.
        keywords: A list of keyword strings to search for.

    Returns:
        True when at least one keyword is present in the text.
    """

    return any(normalize_text(kw) in text for kw in keywords)


class JobClassifier:
    """Classifies a job into one of the system's normalised category constants.

    Classification priority order:
    1. CATEGORY_AI_TRAINING — when AI/annotation keywords are detected **and**
       the hourly rate meets the minimum threshold.
    2. CATEGORY_SOFTWARE_DEV — when development keywords are detected.
    3. CATEGORY_OTHER — fallback for everything else.

    No database access is performed here; the caller supplies all required
    fields so that the classifier remains a pure function of its inputs.
    """

    def classify_job(
        self,
        job_title: str,
        job_description: str,
        hourly_rate: float,
    ) -> str:
        """Determine the category of a job based on its text and hourly rate.

        Args:
            job_title: The title of the job posting.
            job_description: The full description of the job posting.
            hourly_rate: The offered hourly rate in USD (0 when not specified).

        Returns:
            One of the category constants:
            ``CATEGORY_AI_TRAINING``, ``CATEGORY_SOFTWARE_DEV``, or
            ``CATEGORY_OTHER``.
        """

        job_text = normalize_text(f"{job_title} {job_description}")

        if (
            contains_keywords(job_text, _AI_TRAINING_KEYWORDS)
            and hourly_rate >= MIN_AI_TRAINING_RATE
        ):
            return CATEGORY_AI_TRAINING

        if contains_keywords(job_text, _SOFTWARE_DEV_KEYWORDS):
            return CATEGORY_SOFTWARE_DEV

        return CATEGORY_OTHER
