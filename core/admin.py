"""Admin registrations for Freelance Agent database models."""

from django.contrib import admin

from core.database.models import (
	Application,
	Job,
	ProposalTemplate,
	ResumeData,
	Skill,
	SystemLog,
	User,
)


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


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
	"""Read-only admin configuration for centralized system logs."""

	list_display = ("timestamp", "level", "module", "action", "platform", "status")
	list_filter = ("level", "module", "platform", "status", "timestamp")
	search_fields = ("message", "job_url")
	ordering = ("-timestamp",)
	readonly_fields = (
		"timestamp",
		"level",
		"module",
		"action",
		"platform",
		"message",
		"request_payload",
		"response_payload",
		"job_url",
		"stack_trace",
		"status",
	)

	def has_add_permission(self, request):
		"""Disable manual creation from admin UI."""

		return False

	def has_change_permission(self, request, obj=None):
		"""Disable edits while keeping read access in admin."""

		return False

	def has_view_permission(self, request, obj=None):
		"""Allow read-only visibility in admin for authorized staff users."""

		return request.user.is_active and request.user.is_staff

	def has_delete_permission(self, request, obj=None):
		"""Disable deletion from admin UI."""

		return False
