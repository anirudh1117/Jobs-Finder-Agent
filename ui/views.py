"""Django views for the Freelance Agent monitoring interface."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from core.database.models import Application, Job, User as AgentUser
from core.notifications.telegram_notifier import TelegramNotifier
from core.resume.proposal_template_generator import ProposalTemplateGenerator
from core.resume.resume_parser import ResumeParser
from core.resume.resume_upload import ResumeUploader
from core.resume.skill_extractor import SkillExtractor

logger = logging.getLogger(__name__)


class AuthenticatedAgentUserMixin(LoginRequiredMixin):
    """Require login and map Django auth users to the app's profile model.

    The project currently stores domain data in ``core.database.models.User``
    while UI authentication uses Django's built-in auth user model. This mixin
    keeps the UI authenticated and synchronizes a domain user record keyed by
    the logged-in auth user's primary key.
    """

    login_url = "/login/"

    def get_agent_user(self) -> AgentUser:
        """Return the domain user record associated with ``request.user``."""

        auth_user = self.request.user
        agent_user, _ = AgentUser.objects.get_or_create(
            id=auth_user.id,
            defaults={
                "name": auth_user.get_full_name() or auth_user.get_username(),
                "email": auth_user.email or f"user-{auth_user.id}@example.com",
                "resume_path": "",
            },
        )

        updated_fields: list[str] = []
        resolved_name = auth_user.get_full_name() or auth_user.get_username()
        resolved_email = auth_user.email or agent_user.email

        if resolved_name and agent_user.name != resolved_name:
            agent_user.name = resolved_name
            updated_fields.append("name")
        if resolved_email and agent_user.email != resolved_email:
            agent_user.email = resolved_email
            updated_fields.append("email")

        if updated_fields:
            agent_user.save(update_fields=updated_fields)

        return agent_user

    def get_relevant_jobs_queryset(self, agent_user: AgentUser):
        """Return jobs relevant to the logged-in user when possible.

        Jobs are currently stored globally rather than per-user. The UI scopes
        visibility as closely as possible by showing jobs the user has applied
        to and jobs that have been scored as actionable by the pipeline.
        """

        return Job.objects.filter(
            Q(applications__user=agent_user) | Q(score__gt=0)
        ).distinct()


class DashboardView(AuthenticatedAgentUserMixin, TemplateView):
    """Display system overview metrics and recent jobs."""

    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        """Build dashboard summary metrics and recent job list."""

        context = super().get_context_data(**kwargs)
        agent_user = self.get_agent_user()
        jobs_qs = self.get_relevant_jobs_queryset(agent_user)

        total_jobs = jobs_qs.count()
        total_applications = Application.objects.filter(user=agent_user).count()
        jobs_applied = (
            Application.objects.filter(user=agent_user)
            .values("job_id")
            .distinct()
            .count()
        )
        manual_apply_jobs = jobs_qs.filter(score__gte=5).exclude(
            applications__user=agent_user
        ).count()
        recent_jobs = jobs_qs.order_by("-created_at")[:10]

        context.update(
            {
                "total_jobs": total_jobs,
                "total_applications": total_applications,
                "jobs_applied": jobs_applied,
                "manual_apply_jobs": manual_apply_jobs,
                "recent_jobs": recent_jobs,
            }
        )
        return context


class JobsView(AuthenticatedAgentUserMixin, TemplateView):
    """Display fetched jobs with simple platform and score filters."""

    template_name = "jobs.html"

    def get_context_data(self, **kwargs):
        """Return filtered job list and active filter values."""

        context = super().get_context_data(**kwargs)
        agent_user = self.get_agent_user()
        jobs = (
            self.get_relevant_jobs_queryset(agent_user)
            .annotate(application_count=Count("applications"))
            .order_by("-created_at")
        )

        platform = self.request.GET.get("platform", "").strip().lower()
        min_score = self.request.GET.get("score", "").strip()

        if platform:
            jobs = jobs.filter(platform__iexact=platform)

        if min_score:
            try:
                jobs = jobs.filter(score__gte=float(min_score))
            except ValueError:
                messages.warning(self.request, "Invalid score filter ignored.")

        job_rows = []
        for job in jobs:
            if job.applications.filter(user=agent_user).exclude(status=Application.Status.REJECTED).exists():
                status = "AUTO APPLIED"
            elif job.score >= 5:
                status = "MANUAL APPLY"
            else:
                status = "NOT APPLIED"

            job_rows.append({"job": job, "status": status})

        context.update(
            {
                "job_rows": job_rows,
                "active_platform": self.request.GET.get("platform", ""),
                "active_score": self.request.GET.get("score", ""),
            }
        )
        return context


class ApplicationsView(AuthenticatedAgentUserMixin, TemplateView):
    """Display all submitted applications tracked by the system."""

    template_name = "applications.html"

    def get_context_data(self, **kwargs):
        """Return ordered application records for display."""

        context = super().get_context_data(**kwargs)
        agent_user = self.get_agent_user()
        applications = (
            Application.objects.select_related("job", "user")
            .filter(user=agent_user)
            .order_by("-applied_at")
        )
        context["applications"] = applications
        return context


class ResumeUploadView(AuthenticatedAgentUserMixin, View):
    """Accept resume uploads and trigger the resume processing pipeline."""

    template_name = "resume_upload.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the upload form."""

        return render(request, self.template_name)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Persist uploaded file and run resume parsing/extraction workflow."""

        upload = request.FILES.get("resume")
        if upload is None:
            messages.error(request, "Please choose a PDF resume file to upload.")
            return render(request, self.template_name)

        user = self.get_agent_user()
        upload_path = self._save_uploaded_file(upload)

        try:
            uploader = ResumeUploader()
            parser = ResumeParser()
            extractor = SkillExtractor()
            template_generator = ProposalTemplateGenerator()

            stored_path = uploader.save_resume(user_id=user.id, file_path=str(upload_path))
            resume_text = parser.extract_text(stored_path)
            extractor.extract_skills_and_summary(user_id=user.id, resume_text=resume_text)
            template_generator.generate_template(user_id=user.id)
            self._send_resume_uploaded_notification()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Resume upload processing failed.")
            messages.error(request, f"Resume upload failed: {exc}")
            return render(request, self.template_name)

        messages.success(request, "Resume uploaded and processed successfully.")
        return redirect("dashboard")

    @staticmethod
    def _save_uploaded_file(upload) -> Path:
        """Save uploaded resume to local storage and return its path."""

        target_dir = Path(settings.MEDIA_ROOT) / "resumes"
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / upload.name
        with target_path.open("wb+") as destination:
            for chunk in upload.chunks():
                destination.write(chunk)

        return target_path

    @staticmethod
    def _send_resume_uploaded_notification() -> None:
        """Send a best-effort Telegram notification after successful upload."""

        try:
            notifier = TelegramNotifier()
            sent = notifier.send_message(
                "📄 Resume Uploaded\n\n"
                "Your resume has been uploaded successfully.\n\n"
                "The system will now extract skills and prepare proposal templates."
            )
            if not sent:
                logger.warning("Resume upload Telegram notification was not sent.")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send resume upload Telegram notification.")
