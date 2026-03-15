"""Application creation and retrieval helpers."""

from __future__ import annotations

from django.db.models import QuerySet

from core.database.db_manager import DatabaseManager
from core.database.models import Application, Job, User


class ApplicationManager:
    """Manage creation and retrieval of persisted job applications.

    This class is responsible only for recording and retrieving application
    data. It does not generate proposals or perform browser automation.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize the manager with an optional database helper."""

        self._db = db_manager or DatabaseManager()

    def create_application(
        self,
        user_id: int,
        job_id: int,
        proposal_text: str,
        status: str = Application.Status.APPLIED,
    ) -> Application:
        """Create and persist a new application record.

        Args:
            user_id: User primary key.
            job_id: Job primary key.
            proposal_text: Stored proposal content.
            status: Initial application status. Defaults to ``APPLIED``.

        Returns:
            The created Application instance.

        Raises:
            ValueError: If the user has already applied to the job.
            User.DoesNotExist: If the user record does not exist.
            Job.DoesNotExist: If the job record does not exist.
        """

        if self.has_user_applied(user_id=user_id, job_id=job_id):
            raise ValueError(
                f"Application already exists for user_id={user_id} and job_id={job_id}."
            )

        user = User.objects.get(pk=user_id)
        job = Job.objects.get(pk=job_id)
        return self._db.create_application(
            user=user,
            job=job,
            proposal_text=proposal_text,
            status=status,
        )

    def get_application_by_job(self, job_id: int) -> Application | None:
        """Return the most recent application associated with a job."""

        return self._db.get_application_by_job(job_id)

    def has_user_applied(self, user_id: int, job_id: int) -> bool:
        """Return True if the user already has an application for the job."""

        return self._db.has_user_applied(user_id=user_id, job_id=job_id)

    def get_user_applications(self, user_id: int) -> QuerySet[Application]:
        """Return all applications submitted by the user, newest first."""

        return self._db.get_user_applications(user_id=user_id)

    def get_recent_applications(self, limit: int = 20) -> QuerySet[Application]:
        """Return the most recent applications across all users.

        Args:
            limit: Maximum number of application records to return.

        Returns:
            A queryset slice ordered by ``applied_at`` descending.
        """

        return self._db.get_recent_applications(limit=limit)