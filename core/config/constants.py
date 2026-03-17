"""Centralized global constants for the Freelance Agent system.

This module stores stable, non-secret constants that are shared across
multiple modules. These values represent system-wide defaults and labels that
should remain independent from environment-specific runtime configuration.
"""

UPWORK: str = "upwork"
MERCOR: str = "mercor"
OUTLIER: str = "outlier"
REMOTEOK: str = "remoteok"
LINKEDIN: str = "linkedin"
REMOTIVE: str = "remotive"
WEWORKREMOTELY: str = "weworkremotely"
FREELANCER: str = "freelancer"

CATEGORY_SOFTWARE_DEV: str = "software_development"
CATEGORY_AI_TRAINING: str = "ai_training"
CATEGORY_OTHER: str = "other"

MIN_AI_TRAINING_RATE: int = 10
MIN_FIXED_BUDGET: int = 50

JOB_FETCH_INTERVAL_HOURS: int = 0.5
MAX_APPLICATIONS_PER_DAY: int = 10
JOB_MATCH_THRESHOLD: int = 3

DEFAULT_USER_ID: int = 1

DEFAULT_PROPOSAL_LENGTH: int = 1200