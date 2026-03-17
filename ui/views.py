"""Django views for the Freelance Agent monitoring interface."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from core.database.models import (
    Application,
    Job,
    ResumeData,
    Skill,
    TelegramVerification,
    User as AgentUser,
    UserProfile,
)
from core.notifications.telegram_notifier import TelegramNotifier
from core.config.settings import TELEGRAM_BOT_USERNAME
from core.resume.proposal_template_generator import ProposalTemplateGenerator
from core.resume.resume_parser import ResumeParser
from core.resume.resume_upload import ResumeUploader, TARGET_ROLE_CHOICES
from core.resume.skill_extractor import SkillExtractor

logger = logging.getLogger(__name__)


class ResumeUploadForm(forms.Form):
    """Collect a resume file and target roles for upload processing."""

    resume = forms.FileField(required=True)
    target_roles = forms.MultipleChoiceField(
        required=False,
        choices=TARGET_ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple(
            attrs={
                "class": "form-check-input",
            }
        ),
        help_text="Select all roles you want the system to target.",
    )

    def clean_resume(self):
        """Ensure the uploaded file is a supported resume format."""

        upload = self.cleaned_data["resume"]
        ResumeUploader().validate_resume_format(upload.name)
        return upload

    def clean_target_roles(self) -> list[str]:
        """Validate selected target roles against allowed choices."""

        return ResumeUploader.validate_target_roles(self.cleaned_data.get("target_roles", []))


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

        # Ensure an editable profile exists for every authenticated user.
        self.get_user_profile(agent_user=agent_user)

        return agent_user

    def get_user_profile(self, agent_user: AgentUser | None = None) -> UserProfile:
        """Return an editable technical profile for the authenticated user.

        A profile is auto-created when missing so users can edit preferences
        independently of resume uploads.
        """

        auth_user = self.request.user
        agent_user = agent_user or AgentUser.objects.filter(pk=auth_user.id).first()
        profile, _ = UserProfile.objects.get_or_create(
            user=auth_user,
            defaults={
                "headline": auth_user.get_full_name() or auth_user.get_username(),
                "skills": [],
                "roles": [],
                "summary": "",
                "proposal_style_notes": "",
            },
        )

        updated_fields: list[str] = []

        extracted_skills = self._get_extracted_skills(agent_user)
        latest_resume_summary = self._get_latest_resume_summary(agent_user)

        if not profile.skills and extracted_skills:
            profile.skills = extracted_skills
            updated_fields.append("skills")

        if not profile.summary and latest_resume_summary:
            profile.summary = latest_resume_summary
            updated_fields.append("summary")

        if not profile.headline:
            profile.headline = self._build_default_headline(
                auth_user.get_full_name() or auth_user.get_username(),
                profile.skills,
            )
            updated_fields.append("headline")

        if updated_fields:
            profile.save(update_fields=updated_fields + ["updated_at"])

        return profile

    @staticmethod
    def _get_extracted_skills(agent_user: AgentUser | None) -> list[str]:
        """Return extracted skill names from the domain user record."""

        if agent_user is None:
            return []
        return list(
            Skill.objects.filter(user=agent_user)
            .order_by("-weight", "skill_name")
            .values_list("skill_name", flat=True)
        )

    @staticmethod
    def _get_latest_resume_summary(agent_user: AgentUser | None) -> str:
        """Return the most recent extracted summary if one exists."""

        if agent_user is None:
            return ""
        latest_resume = (
            ResumeData.objects.filter(user=agent_user)
            .order_by("-created_at")
            .first()
        )
        return latest_resume.summary if latest_resume else ""

    @staticmethod
    def _build_default_headline(display_name: str, skills: list[str]) -> str:
        """Build a reasonable default headline for proposal/profile use."""

        top_skills = [skill.strip() for skill in skills[:3] if skill.strip()]
        if top_skills:
            return f"{' | '.join(top_skills)} Developer"
        return display_name

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

        return render(request, self.template_name, {"form": ResumeUploadForm()})

    def post(self, request: HttpRequest) -> HttpResponse:
        """Persist uploaded file and run resume parsing/extraction workflow."""

        form = ResumeUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        upload = form.cleaned_data["resume"]
        selected_roles = form.cleaned_data.get("target_roles", [])

        user = self.get_agent_user()
        upload_path = self._save_uploaded_file(upload)

        try:
            uploader = ResumeUploader()
            parser = ResumeParser()
            extractor = SkillExtractor()
            template_generator = ProposalTemplateGenerator()

            stored_path = uploader.save_resume(user_id=user.id, file_path=str(upload_path))
            resume_text = parser.extract_text(stored_path)
            extracted = extractor.extract_skills_and_summary(user_id=user.id, resume_text=resume_text)

            profile = self.get_user_profile(agent_user=user)
            profile.skills = extracted.get("skills", []) or []
            profile.summary = str(extracted.get("summary", "") or "").strip()
            profile.merge_roles(selected_roles)
            if not profile.headline:
                profile.headline = self._build_default_headline(user.name, profile.skills)
                profile.save(update_fields=["skills", "summary", "roles", "headline", "updated_at"])
            else:
                profile.save(update_fields=["skills", "summary", "roles", "updated_at"])

            template_generator.generate_template(user_id=user.id)
            self._send_resume_uploaded_notification()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Resume upload processing failed.")
            messages.error(request, f"Resume upload failed: {exc}")
            return render(request, self.template_name, {"form": form})

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


class ProfileView(AuthenticatedAgentUserMixin, View):
    """Render and update editable user technical profile fields."""

    template_name = "profile.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render profile form for the logged-in user."""

        profile = self.get_user_profile(agent_user=self.get_agent_user())
        context = {
            "profile": profile,
            "skills_text": "\n".join(profile.skills or []),
            "roles_text": "\n".join(profile.roles or []),
        }
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest) -> HttpResponse:
        """Validate and persist profile edits from user input."""

        agent_user = self.get_agent_user()
        profile = self.get_user_profile(agent_user=agent_user)

        headline = request.POST.get("headline", "").strip()
        summary = request.POST.get("summary", "").strip()
        proposal_style_notes = request.POST.get("proposal_style_notes", "").strip()
        skills_text = request.POST.get("skills", "")
        roles_text = request.POST.get("roles", "")
        hourly_rate_raw = request.POST.get("hourly_rate", "").strip()

        hourly_rate: Decimal | None = None
        if hourly_rate_raw:
            try:
                hourly_rate = Decimal(hourly_rate_raw)
            except (InvalidOperation, ValueError):
                messages.error(request, "Hourly rate must be a valid number.")
                context = {
                    "profile": profile,
                    "skills_text": skills_text,
                    "roles_text": roles_text,
                }
                return render(request, self.template_name, context)

        profile.headline = headline or self._build_default_headline(
            self.request.user.get_full_name() or self.request.user.get_username(),
            self._parse_list_input(skills_text),
        )
        profile.summary = summary
        profile.proposal_style_notes = proposal_style_notes or None
        profile.skills = self._parse_list_input(skills_text)
        profile.roles = self._parse_list_input(roles_text)
        profile.hourly_rate = hourly_rate
        profile.save()

        self._sync_profile_skills(agent_user=agent_user, skills=profile.skills)
        self._sync_profile_summary(agent_user=agent_user, summary=profile.summary)

        messages.success(request, "Profile updated successfully.")
        return redirect("profile")

    @staticmethod
    def _parse_list_input(value: str) -> list[str]:
        """Convert comma/newline-separated text into a normalized string list."""

        items = []
        for raw in value.replace(",", "\n").splitlines():
            cleaned = raw.strip()
            if cleaned:
                items.append(cleaned)
        return items

    @staticmethod
    def _sync_profile_skills(agent_user: AgentUser, skills: list[str]) -> None:
        """Replace extracted skill rows with the latest profile-edited skills."""

        Skill.objects.filter(user=agent_user).delete()
        Skill.objects.bulk_create(
            [Skill(user=agent_user, skill_name=skill) for skill in skills if skill.strip()]
        )

    @staticmethod
    def _sync_profile_summary(agent_user: AgentUser, summary: str) -> None:
        """Persist edited summary to the latest resume record when available."""

        latest_resume = (
            ResumeData.objects.filter(user=agent_user)
            .order_by("-created_at")
            .first()
        )
        if latest_resume is not None and latest_resume.summary != summary:
            latest_resume.summary = summary
            latest_resume.save(update_fields=["summary"])


class ConnectTelegramView(AuthenticatedAgentUserMixin, View):
    """Display Telegram connection instructions for the bot-first confirmation flow."""

    template_name = "connect_telegram.html"
    telegram_bot_username = TELEGRAM_BOT_USERNAME

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render a bot-open page and show current Telegram connection state."""

        profile = self.get_user_profile(agent_user=self.get_agent_user())

        bot_username = str(self.telegram_bot_username).strip().lstrip("@")

        telegram_deep_link = f"https://t.me/{bot_username}"
        telegram_app_deep_link = f"tg://resolve?domain={bot_username}"
        telegram_web_link = f"https://web.telegram.org/k/#@{quote(bot_username)}"

        context = {
            "telegram_deep_link": telegram_deep_link,
            "telegram_app_deep_link": telegram_app_deep_link,
            "telegram_web_link": telegram_web_link,
            "bot_username": bot_username,
            "is_telegram_connected": bool(profile.telegram_chat_id),
            "linked_chat_id": profile.telegram_chat_id or "",
        }

        return render(request, self.template_name, context)


class ConnectTelegramConfirmView(AuthenticatedAgentUserMixin, View):
    """Finalize Telegram linking for the currently authenticated user."""

    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        """Confirm a pending Telegram verification and attach its chat ID to the user."""

        verification = TelegramVerification.objects.filter(token=token).first()
        if verification is None:
            messages.error(request, "This Telegram confirmation link is invalid.")
            return redirect("connect-telegram")

        if verification.is_used:
            messages.error(request, "This Telegram confirmation link has already been used.")
            return redirect("connect-telegram")

        if verification.is_expired():
            messages.error(request, "This Telegram confirmation link has expired. Start again from Telegram.")
            return redirect("connect-telegram")

        if not verification.chat_id:
            messages.error(request, "Telegram chat details are missing. Start again from Telegram.")
            return redirect("connect-telegram")

        existing_owner = UserProfile.objects.filter(
            telegram_chat_id=verification.chat_id,
        ).exclude(user=request.user).first()
        if existing_owner is not None:
            messages.error(request, "This Telegram account is already linked to another user.")
            return redirect("connect-telegram")

        profile = self.get_user_profile(agent_user=self.get_agent_user())
        profile.telegram_chat_id = verification.chat_id
        profile.save(update_fields=["telegram_chat_id", "updated_at"])

        verification.user = request.user
        verification.is_used = True
        verification.save(update_fields=["user", "is_used"])

        TelegramVerification.objects.filter(
            chat_id=verification.chat_id,
            is_used=False,
        ).exclude(pk=verification.pk).delete()

        try:
            notifier = TelegramNotifier()
            notifier.send_message(
                "Telegram connected successfully. You will now receive job alerts.",
                chat_id=verification.chat_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send Telegram confirmation message.")

        logger.info("Telegram account linked for user=%s", request.user.username)
        messages.success(request, "Telegram connected successfully.")
        return redirect("connect-telegram")

