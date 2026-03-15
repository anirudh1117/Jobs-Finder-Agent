"""Application status transition helpers."""

from __future__ import annotations

from django.db.models import QuerySet

from core.database.db_manager import DatabaseManager
from core.database.models import Application


class ApplicationStatusUpdater:
    """Update and retrieve application records by lifecycle status.

    This class validates status values against the Application model choices and
    persists all updates through the shared database helper.
    """

    _ALLOWED_STATUSES = {
        Application.Status.APPLIED,
        Application.Status.VIEWED,
        Application.Status.REPLIED,
        Application.Status.INTERVIEW,
        Application.Status.REJECTED,
    }

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize the updater with an optional database helper."""

        self._db = db_manager or DatabaseManager()

    def update_status(self, application_id: int, new_status: str) -> Application:
        """Validate and persist a new status value for an application.

        Args:
            application_id: Application primary key.
            new_status: New lifecycle status.

        Returns:
            The updated Application instance.

        Raises:
            ValueError: If the status is invalid or the application is missing.
        """

        if new_status not in self._ALLOWED_STATUSES:
            raise ValueError(
                f"Invalid application status '{new_status}'. Allowed values: "
                f"{sorted(self._ALLOWED_STATUSES)}"
            )

        application = self._db.get_application_by_id(application_id)
        if application is None:
            raise ValueError(f"Application with id={application_id} does not exist.")

        return self._db.update_application_status(application=application, status=new_status)

    def mark_viewed(self, application_id: int) -> Application:
        """Update an application status to ``VIEWED``."""

        return self.update_status(application_id, Application.Status.VIEWED)

    def mark_replied(self, application_id: int) -> Application:
        """Update an application status to ``REPLIED``."""

        return self.update_status(application_id, Application.Status.REPLIED)

    def mark_interview(self, application_id: int) -> Application:
        """Update an application status to ``INTERVIEW``."""

        return self.update_status(application_id, Application.Status.INTERVIEW)

    def mark_rejected(self, application_id: int) -> Application:
        """Update an application status to ``REJECTED``."""

        return self.update_status(application_id, Application.Status.REJECTED)

    def get_applications_by_status(self, status: str) -> QuerySet[Application]:
        """Return applications filtered by lifecycle status.

        Args:
            status: One of the Application status choice values.

        Returns:
            QuerySet of matching applications ordered by newest first.

        Raises:
            ValueError: If the status is invalid.
        """

        if status not in self._ALLOWED_STATUSES:
            raise ValueError(
                f"Invalid application status '{status}'. Allowed values: "
                f"{sorted(self._ALLOWED_STATUSES)}"
            )

        return self._db.get_applications_by_status(status=status)