"""Django ORM models for the Freelance Agent database layer."""

from __future__ import annotations

from django.db import models

from core.config.constants import (
    CATEGORY_AI_TRAINING,
    CATEGORY_OTHER,
    CATEGORY_SOFTWARE_DEV,
    LINKEDIN,
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

    class Category(models.TextChoices):
        """Supported normalized job categories."""

        SOFTWARE_DEV = CATEGORY_SOFTWARE_DEV, "Software Development"
        AI_TRAINING = CATEGORY_AI_TRAINING, "AI Training"
        OTHER = CATEGORY_OTHER, "Other"

    title = models.CharField(max_length=255)
    description = models.TextField()
    platform = models.CharField(max_length=50, choices=Platform.choices)
    job_url = models.URLField(max_length=1000)
    budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    category = models.CharField(max_length=64, choices=Category.choices, default=Category.OTHER)
    score = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["job_url"], name="core_job_url_idx"),
            models.Index(fields=["platform"], name="core_job_platform_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["job_url"], name="core_unique_job_url"),
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