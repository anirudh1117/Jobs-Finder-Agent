"""Resume processing package for the Freelance Agent system.

Provides resume upload, text extraction, skill extraction, and
proposal template generation in a loosely coupled pipeline.
"""

from core.resume.proposal_template_generator import ProposalTemplateGenerator
from core.resume.resume_parser import ResumeParser
from core.resume.resume_upload import ResumeUploader
from core.resume.skill_extractor import SkillExtractor

__all__ = [
    "ProposalTemplateGenerator",
    "ResumeParser",
    "ResumeUploader",
    "SkillExtractor",
]
