"""Builds structured inputs required for proposal generation."""

from __future__ import annotations

from typing import Any

from core.database.db_manager import DatabaseManager
from core.database.models import Job, ResumeData


class ProposalBuilder:
    """Assembles user and job context into a single generation payload.

    This class keeps database retrieval logic separate from text generation so
    prompt construction and LLM calls remain focused and easy to test.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize the builder with an optional database manager."""

        self._db = db_manager or DatabaseManager()

    def get_user_context(self, user_id: int) -> dict[str, Any]:
        """Fetch summary, skills, and base template for a given user.

        Args:
            user_id: Primary key of the user.

        Returns:
            A dictionary containing:
            {
                "summary": str,
                "skills": list[str],
                "template": str,
            }

        Raises:
            ValueError: If required resume data does not exist.
        """

        latest_resume = (
            ResumeData.objects.filter(user_id=user_id)
            .order_by("-created_at")
            .first()
        )
        if latest_resume is None:
            raise ValueError(
                f"No resume summary found for user {user_id}. "
                "Run resume extraction before generating proposals."
            )

        skills = list(
            self._db.get_user_skills(user_id).values_list("skill_name", flat=True)
        )

        template_obj = self._db.get_proposal_template(user_id)
        template_text = template_obj.template_text if template_obj else ""

        return {
            "summary": latest_resume.summary,
            "skills": skills,
            "template": template_text,
        }

    def build_job_context(self, job: Job) -> dict[str, Any]:
        """Extract key fields from a job model instance.

        Args:
            job: A persisted Job model instance.

        Returns:
            A dictionary containing normalized job details used by the generator.
        """

        return {
            "title": job.title,
            "description": job.description,
            "platform": job.platform,
            "budget": float(job.budget) if job.budget is not None else 0.0,
            "hourly_rate": float(job.hourly_rate) if job.hourly_rate is not None else 0.0,
        }

    @staticmethod
    def build_proposal_input(
        user_context: dict[str, Any],
        job_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine user and job context into a single generation payload.

        Args:
            user_context: Output of ``get_user_context``.
            job_context: Output of ``build_job_context``.

        Returns:
            A dictionary with two top-level keys:
            {
                "user_context": {...},
                "job_context": {...},
            }
        """

        return {
            "user_context": user_context,
            "job_context": job_context,
        }
