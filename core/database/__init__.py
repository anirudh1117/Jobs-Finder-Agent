"""Database layer package for the Freelance Agent system."""

from core.database.db_manager import DatabaseManager
from core.database.models import Application, Job, ProposalTemplate, ResumeData, Skill, User

__all__ = [
    "Application",
    "DatabaseManager",
    "Job",
    "ProposalTemplate",
    "ResumeData",
    "Skill",
    "User",
]