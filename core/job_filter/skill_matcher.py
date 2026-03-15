"""Determines whether a job description matches a user's skill set."""

from __future__ import annotations

import re
from typing import List

from core.database.db_manager import DatabaseManager


def normalize_text(text: str) -> str:
    """Convert text to lowercase and collapse runs of whitespace to a single space.

    Args:
        text: Any string to normalise.

    Returns:
        The cleaned, lowercase version of the input.
    """

    return re.sub(r"\s+", " ", text.lower()).strip()


class SkillMatcher:
    """Matches a job's text content against the skills stored for a user.

    Single responsibility: given a job title + description and a user's skill
    list, report which skills were found and how strong the overlap is.
    Database reads are delegated to DatabaseManager; scoring is handled by
    the separate JobScorer class.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialise with an optional DatabaseManager for dependency injection.

        Args:
            db_manager: A DatabaseManager instance to use for skill lookups.
                        A new instance is created when not provided.
        """

        self._db = db_manager or DatabaseManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_user_skills(self, user_id: int) -> List[str]:
        """Retrieve and normalise the skill names for a given user.

        Args:
            user_id: The primary key of the target User.

        Returns:
            A list of lowercase skill name strings, ordered by weight
            descending then name ascending (delegated to DatabaseManager).
        """

        skills_qs = self._db.get_user_skills(user_id)
        return [normalize_text(s) for s in skills_qs.values_list("skill_name", flat=True)]

    def match_job_skills(
        self,
        job_title: str,
        job_description: str,
        user_skills: List[str],
    ) -> dict:
        """Check which of the user's skills appear in the job text.

        The match is purely textual: a skill is considered matched when its
        normalised form appears anywhere in the combined job title and
        description.  This is intentionally simple and deterministic so that
        results can be reproduced without any external service.

        Args:
            job_title: The title of the job posting.
            job_description: The full description of the job posting.
            user_skills: A list of normalised (lowercase) skill names.

        Returns:
            A dict with three keys:

            * ``matched_skills`` (List[str]): skills found in the job text.
            * ``match_count`` (int): number of matched skills.
            * ``match_ratio`` (float): matched_count / total_user_skills,
              or 0.0 when the user has no skills on record.
        """

        job_text = normalize_text(f"{job_title} {job_description}")

        matched: List[str] = [skill for skill in user_skills if skill in job_text]

        total = len(user_skills)
        ratio = len(matched) / total if total > 0 else 0.0

        return {
            "matched_skills": matched,
            "match_count": len(matched),
            "match_ratio": round(ratio, 4),
        }
