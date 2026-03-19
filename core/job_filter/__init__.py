"""Job filtering package for the Freelance Agent system.

Provides skill matching, job classification, and relevance scoring for jobs
already stored in the database.  This package performs no fetching of its own.
"""

from core.job_filter.job_classifier import JobClassifier
from core.job_filter.pipeline_debug import JobPreFilter, PipelineDebugReport
from core.job_filter.job_scoring import JobScorer
from core.job_filter.skill_matcher import SkillMatcher
from core.job_filter.user_job_relevance import UserJobRelevanceScorer

__all__ = [
    "JobClassifier",
    "JobPreFilter",
    "PipelineDebugReport",
    "JobScorer",
    "SkillMatcher",
    "UserJobRelevanceScorer",
]
