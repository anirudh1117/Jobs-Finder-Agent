"""Bridge module exposing Django models for the core app."""

from core.database.models import Application, Job, ProposalTemplate, ResumeData, Skill, User

__all__ = [
	"Application",
	"Job",
	"ProposalTemplate",
	"ResumeData",
	"Skill",
	"User",
]
