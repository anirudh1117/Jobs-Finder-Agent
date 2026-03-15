"""Database helper service for common Django ORM operations."""

from __future__ import annotations

from typing import Any, Mapping

from django.db.models import QuerySet

from core.database.models import Application, Job, ProposalTemplate, Skill, User


class DatabaseManager:
    """Encapsulates common database operations used across the system."""

    def create_job(self, job_data: Mapping[str, Any]) -> Job:
        """Create or update a job record using its URL as the stable key.

        Args:
            job_data: Normalized job fields compatible with the Job model.

        Returns:
            The created or updated Job instance.

        Raises:
            ValueError: If the required job_url field is missing.
        """

        if "job_url" not in job_data or not job_data["job_url"]:
            raise ValueError("job_data must include a non-empty job_url value.")

        job_url = str(job_data["job_url"])
        defaults = {key: value for key, value in job_data.items() if key != "job_url"}
        job, _ = Job.objects.update_or_create(job_url=job_url, defaults=defaults)
        return job

    def get_job_by_url(self, job_url: str) -> Job | None:
        """Return the job matching the provided URL, if it exists."""

        return Job.objects.filter(job_url=job_url).first()

    def save_application(self, user: User, job: Job, proposal_text: str) -> Application:
        """Create and persist a new application for the given user and job."""

        return Application.objects.create(
            user=user,
            job=job,
            proposal_text=proposal_text,
            status=Application.Status.APPLIED,
        )

    def create_application(
        self,
        user: User,
        job: Job,
        proposal_text: str,
        status: str = Application.Status.APPLIED,
    ) -> Application:
        """Create and persist a new application with an explicit status.

        Args:
            user: User associated with the application.
            job: Job associated with the application.
            proposal_text: Proposal content stored with the application.
            status: Application lifecycle status value.

        Returns:
            The created Application instance.
        """

        return Application.objects.create(
            user=user,
            job=job,
            proposal_text=proposal_text,
            status=status,
        )

    def get_application_by_job(self, job_id: int) -> Application | None:
        """Return the most recent application associated with a job, if any."""

        return Application.objects.filter(job_id=job_id).order_by("-applied_at").first()

    def has_user_applied(self, user_id: int, job_id: int) -> bool:
        """Return True if the user already has an application for the job."""

        return Application.objects.filter(user_id=user_id, job_id=job_id).exists()

    def get_user_applications(self, user_id: int) -> QuerySet[Application]:
        """Return all applications for a user sorted by newest first."""

        return Application.objects.filter(user_id=user_id).order_by("-applied_at")

    def get_recent_applications(self, limit: int = 20) -> QuerySet[Application]:
        """Return the most recent application records across all users."""

        return Application.objects.all().order_by("-applied_at")[:limit]

    def get_application_by_id(self, application_id: int) -> Application | None:
        """Return an application by primary key, if it exists."""

        return Application.objects.filter(pk=application_id).first()

    def update_application_status(self, application: Application, status: str) -> Application:
        """Persist a new status value on an existing application."""

        application.status = status
        application.save(update_fields=["status"])
        return application

    def get_applications_by_status(self, status: str) -> QuerySet[Application]:
        """Return applications filtered by lifecycle status."""

        return Application.objects.filter(status=status).order_by("-applied_at")

    def get_pending_jobs(self) -> QuerySet[Job]:
        """Return jobs that do not yet have any application records."""

        return Job.objects.filter(applications__isnull=True).distinct()

    def get_applied_jobs(self) -> QuerySet[Job]:
        """Return jobs that already have one or more application records."""

        return Job.objects.filter(applications__isnull=False).distinct()

    def get_user_skills(self, user_id: int) -> QuerySet[Skill]:
        """Return all skills associated with the provided user identifier."""

        return Skill.objects.filter(user_id=user_id).order_by("-weight", "skill_name")

    def get_proposal_template(self, user_id: int) -> ProposalTemplate | None:
        """Return the highest-priority proposal template for a user.

        The template with the highest success rate is preferred, with the most
        recent template used as a tiebreaker.
        """

        return ProposalTemplate.objects.filter(user_id=user_id).order_by(
            "-success_rate",
            "-created_at",
        ).first()