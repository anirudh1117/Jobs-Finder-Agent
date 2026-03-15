"""Job filtering package for the Freelance Agent system.

Provides skill matching, job classification, and relevance scoring for jobs
already stored in the database.  This package performs no fetching of its own.
"""

from core.job_filter.job_classifier import JobClassifier
from core.job_filter.job_scoring import JobScorer
from core.job_filter.skill_matcher import SkillMatcher

__all__ = [
    "JobClassifier",
    "JobScorer",
    "SkillMatcher",
]
