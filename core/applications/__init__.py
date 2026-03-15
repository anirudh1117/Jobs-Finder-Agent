"""Application tracking package for the Freelance Agent system."""

from core.applications.application_manager import ApplicationManager
from core.applications.status_updater import ApplicationStatusUpdater

__all__ = ["ApplicationManager", "ApplicationStatusUpdater"]