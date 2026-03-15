"""Calculates a relevance score for each job and decides whether to apply."""

from __future__ import annotations

from core.config.constants import CATEGORY_AI_TRAINING, CATEGORY_SOFTWARE_DEV

# Thresholds used in scoring.
_BUDGET_HIGH_THRESHOLD: float = 500.0
_BUDGET_MID_THRESHOLD: float = 200.0
_HOURLY_HIGH_THRESHOLD: float = 50.0
_HOURLY_MID_THRESHOLD: float = 20.0

# Minimum score required to trigger an automatic application.
_AUTO_APPLY_THRESHOLD: float = 5.0


class JobScorer:
    """Computes a deterministic relevance score for a job.

    The score is the sum of four independent components so that each factor
    can be reasoned about and tested in isolation:

    * **Skill match score** — how well the job aligns with the user's skills.
    * **Category bonus** — extra weight for high-value categories.
    * **Budget bonus** — reward for higher fixed-price budgets.
    * **Hourly bonus** — reward for higher hourly rates.

    No database access or external calls are performed; all inputs are passed
    explicitly so the scorer is a pure, easily testable function.
    """

    def calculate_job_score(
        self,
        skill_match_ratio: float,
        category: str,
        budget: float,
        hourly_rate: float,
    ) -> float:
        """Calculate the total relevance score for a job.

        Score components:

        * Skill match: ``skill_match_ratio * 5``
        * Category bonus: +5 for AI training, +3 for software dev, +0 otherwise
        * Budget bonus: +2 if budget ≥ 500, +1 if budget ≥ 200
        * Hourly bonus: +2 if hourly_rate ≥ 50, +1 if hourly_rate ≥ 20

        Args:
            skill_match_ratio: Float in [0, 1] from SkillMatcher.match_job_skills.
            category: One of the CATEGORY_* constants from constants.py.
            budget: Fixed-price budget in USD (0 when not applicable).
            hourly_rate: Offered hourly rate in USD (0 when not applicable).

        Returns:
            The total relevance score as a float.
        """

        skill_score = self._skill_score(skill_match_ratio)
        category_bonus = self._category_bonus(category)
        budget_bonus = self._budget_bonus(budget)
        hourly_bonus = self._hourly_bonus(hourly_rate)

        return skill_score + category_bonus + budget_bonus + hourly_bonus

    def should_apply(self, score: float) -> bool:
        """Return True when the job score is high enough to warrant applying.

        Args:
            score: The value returned by ``calculate_job_score``.

        Returns:
            True if ``score`` is at or above the auto-apply threshold (5.0).
        """

        return score >= _AUTO_APPLY_THRESHOLD

    # ------------------------------------------------------------------
    # Private component helpers – isolated for unit-test clarity
    # ------------------------------------------------------------------

    @staticmethod
    def _skill_score(skill_match_ratio: float) -> float:
        """Return the skill-match component of the total score.

        Args:
            skill_match_ratio: Float in [0, 1] representing matched / total skills.

        Returns:
            skill_match_ratio multiplied by 5.
        """

        return skill_match_ratio * 5

    @staticmethod
    def _category_bonus(category: str) -> float:
        """Return the category bonus component.

        Args:
            category: One of the CATEGORY_* constants.

        Returns:
            5 for AI training, 3 for software development, 0 otherwise.
        """

        if category == CATEGORY_AI_TRAINING:
            return 5.0
        if category == CATEGORY_SOFTWARE_DEV:
            return 3.0
        return 0.0

    @staticmethod
    def _budget_bonus(budget: float) -> float:
        """Return the fixed-budget component.

        Args:
            budget: Fixed-price budget in USD.

        Returns:
            2 for budgets ≥ 500, 1 for budgets ≥ 200, 0 otherwise.
        """

        if budget >= _BUDGET_HIGH_THRESHOLD:
            return 2.0
        if budget >= _BUDGET_MID_THRESHOLD:
            return 1.0
        return 0.0

    @staticmethod
    def _hourly_bonus(hourly_rate: float) -> float:
        """Return the hourly-rate component.

        Args:
            hourly_rate: Offered hourly rate in USD.

        Returns:
            2 for rates ≥ 50, 1 for rates ≥ 20, 0 otherwise.
        """

        if hourly_rate >= _HOURLY_HIGH_THRESHOLD:
            return 2.0
        if hourly_rate >= _HOURLY_MID_THRESHOLD:
            return 1.0
        return 0.0
