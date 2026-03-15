"""Admin registrations for Freelance Agent database models."""

from django.contrib import admin

from core.database.models import Application, Job, ProposalTemplate, ResumeData, Skill, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
	"""Admin configuration for freelancer user records."""

	list_display = ("name", "email", "resume_path", "created_at")
	search_fields = ("name", "email")
	ordering = ("-created_at",)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
	"""Admin configuration for extracted user skills."""

	list_display = ("skill_name", "user")
	search_fields = ("skill_name", "user__name", "user__email")


@admin.register(ResumeData)
class ResumeDataAdmin(admin.ModelAdmin):
	"""Admin configuration for parsed resume records."""

	list_display = ("user", "created_at")
	search_fields = ("user__name", "user__email", "summary")
	ordering = ("-created_at",)


@admin.register(ProposalTemplate)
class ProposalTemplateAdmin(admin.ModelAdmin):
	"""Admin configuration for reusable proposal templates."""

	list_display = ("user", "success_rate", "created_at")
	search_fields = ("user__name", "user__email", "template_text")
	ordering = ("-created_at",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
	"""Admin configuration for fetched jobs."""

	list_display = ("title", "platform", "budget", "hourly_rate", "score", "created_at")
	list_filter = ("platform", "score", "created_at")
	search_fields = ("title", "description")
	ordering = ("-created_at",)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
	"""Admin configuration for application tracking records."""

	list_display = ("job", "user", "status", "applied_at")
	list_filter = ("status", "applied_at")
	search_fields = ("job__title", "user__name", "user__email")
	ordering = ("-applied_at",)
