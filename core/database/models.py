"""Django ORM models for the Freelance Agent database layer."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User as AuthUser
from django.db import models
from django.utils import timezone

from core.config.constants import (
    CATEGORY_AI_TRAINING,
    CATEGORY_OTHER,
    CATEGORY_SOFTWARE_DEV,
    LINKEDIN,
    NAUKRI,
    MERCOR,
    OUTLIER,
    REMOTEOK,
    UPWORK,
)


class User(models.Model):
    """Represents a freelancer profile stored in the system."""

    name = models.CharField(max_length=255)
    email = models.EmailField()
    resume_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class UserProfile(models.Model):
    """Editable technical profile used by automation and proposal generation."""

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, on_delete=models.CASCADE, related_name="profiles")
    headline = models.CharField(max_length=255, blank=True)
    skills = models.JSONField(default=list, blank=True)
    roles = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True)
    proposal_style_notes = models.TextField(blank=True, null=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    telegram_chat_id = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Profile<{self.user.username}>"

    def merge_roles(self, roles: list[str]) -> list[str]:
        """Merge new role values into the stored JSON list without duplicates."""

        merged_roles = list(self.roles or [])
        for role in roles:
            cleaned_role = str(role).strip()
            if cleaned_role and cleaned_role not in merged_roles:
                merged_roles.append(cleaned_role)
        self.roles = merged_roles
        return merged_roles


class Skill(models.Model):
    """Represents an extracted or user-defined skill for a freelancer."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="skills")
    skill_name = models.CharField(max_length=255)
    weight = models.PositiveIntegerField(default=1)

    def __str__(self) -> str:
        return f"{self.skill_name} ({self.user.name})"


class ResumeData(models.Model):
    """Stores structured resume information extracted from an uploaded resume."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="resume_data")
    summary = models.TextField()
    extracted_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Resume data for {self.user.name}"


class ProposalTemplate(models.Model):
    """Stores reusable proposal templates associated with a freelancer."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="proposal_templates")
    template_text = models.TextField()
    success_rate = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Proposal template for {self.user.name}"


class Job(models.Model):
    """Stores normalized job postings fetched from supported platforms."""

    class Platform(models.TextChoices):
        """Supported external job platforms."""

        UPWORK = UPWORK, "Upwork"
        MERCOR = MERCOR, "Mercor"
        OUTLIER = OUTLIER, "Outlier"
        REMOTEOK = REMOTEOK, "RemoteOK"
        LINKEDIN = LINKEDIN, "LinkedIn"
        NAUKRI = NAUKRI, "Naukri"

    class Category(models.TextChoices):
        """Supported normalized job categories."""

        SOFTWARE_DEV = CATEGORY_SOFTWARE_DEV, "Software Development"
        AI_TRAINING = CATEGORY_AI_TRAINING, "AI Training"
        OTHER = CATEGORY_OTHER, "Other"

    class JobType(models.TextChoices):
        """Supported normalized job type values used for filtering."""

        CONTRACT = "contract", "Contract"
        FULL_TIME = "full_time", "Full Time"
        PART_TIME = "part_time", "Part Time"
        FREELANCE = "freelance", "Freelance"

    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField()
    platform = models.CharField(max_length=50, choices=Platform.choices)
    job_url = models.URLField(max_length=1000, unique=True)
    budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    job_type = models.CharField(
        max_length=32,
        choices=JobType.choices,
        default=JobType.CONTRACT,
    )
    skills = models.JSONField(default=list, blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    category = models.CharField(max_length=64, choices=Category.choices, default=Category.OTHER)
    score = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["job_url"], name="core_job_url_idx"),
            models.Index(fields=["platform"], name="core_job_platform_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.platform})"


class Application(models.Model):
    """Tracks a user's application and proposal for a specific job."""

    class Status(models.TextChoices):
        """Application lifecycle status values."""

        APPLIED = "APPLIED", "Applied"
        VIEWED = "VIEWED", "Viewed"
        REPLIED = "REPLIED", "Replied"
        INTERVIEW = "INTERVIEW", "Interview"
        REJECTED = "REJECTED", "Rejected"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="applications")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="applications")
    proposal_text = models.TextField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.APPLIED)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-applied_at"]

    def __str__(self) -> str:
        return f"{self.user.name} -> {self.job.title} ({self.status})"


class UserJobMatch(models.Model):
    """Stores per-user job match state against globally persisted jobs."""

    class ApplicationStatus(models.TextChoices):
        """Lifecycle values for a user's relationship to a matched job."""

        NOT_APPLIED = "not_applied", "Not Applied"
        AUTO_APPLIED = "auto_applied", "Auto Applied"
        MANUAL_APPLY_REQUIRED = "manual_apply_required", "Manual Apply Required"

    user = models.ForeignKey(AuthUser, on_delete=models.CASCADE, related_name="job_matches")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="user_matches")
    match_score = models.IntegerField()
    proposal_text = models.TextField(null=True, blank=True)
    application_status = models.CharField(
        max_length=32,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.NOT_APPLIED,
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-match_score", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "job"], name="core_unique_user_job_match"),
        ]
        indexes = [
            models.Index(fields=["user"], name="core_match_user_idx"),
            models.Index(fields=["job"], name="core_match_job_idx"),
            models.Index(fields=["match_score"], name="core_match_score_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} -> {self.job.title} ({self.match_score})"


class SystemLog(models.Model):
    """Stores centralized system events for monitoring and debugging."""

    class Level(models.TextChoices):
        """Supported severity levels for system logs."""

        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        """Execution outcome values for system logs."""

        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=16, choices=Level.choices)
    module = models.CharField(max_length=100)
    action = models.CharField(max_length=100)
    platform = models.CharField(max_length=64, null=True, blank=True)
    message = models.TextField()
    request_payload = models.JSONField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    job_url = models.TextField(null=True, blank=True)
    stack_trace = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"], name="core_syslog_time_idx"),
            models.Index(fields=["level"], name="core_syslog_level_idx"),
            models.Index(fields=["module"], name="core_syslog_module_idx"),
            models.Index(fields=["status"], name="core_syslog_status_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.level}] {self.module}.{self.action} ({self.status})"


class TelegramVerification(models.Model):
    """Stores pending and completed Telegram account linking attempts."""

    user = models.ForeignKey(
        AuthUser,
        on_delete=models.CASCADE,
        related_name="telegram_verifications",
        null=True,
        blank=True,
    )
    token = models.CharField(max_length=255, unique=True)
    chat_id = models.CharField(max_length=50, blank=True, default="")
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["token"], name="core_telegram_token_idx"),
            models.Index(fields=["is_used"], name="core_telegram_used_idx"),
            models.Index(fields=["chat_id"], name="core_telegram_chat_idx"),
        ]

    def is_expired(self) -> bool:
        """Return whether the verification request is older than 10 minutes."""

        return timezone.now() - self.created_at > timedelta(minutes=10)

    def is_pending(self) -> bool:
        """Return whether this verification is still awaiting web confirmation."""

        return not self.is_used and not self.is_expired()

    def __str__(self) -> str:
        owner = self.user.username if self.user else "unassigned"
        return f"TelegramVerification<{owner}, chat_id={self.chat_id or 'unknown'}, used={self.is_used}>"


class SerpAPIUsage(models.Model):
    """Tracks SerpAPI usage count per day for quota enforcement."""

    id = models.AutoField(primary_key=True)
    date = models.DateField(unique=True)
    month = models.CharField(max_length=7, db_index=True)  # YYYY-MM
    request_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["date"], name="core_serpapi_date_idx"),
            models.Index(fields=["month"], name="core_serpapi_month_idx"),
        ]

    def __str__(self) -> str:
        return f"SerpAPIUsage<{self.date} requests={self.request_count}>"