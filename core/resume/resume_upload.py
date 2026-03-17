"""Handles resume file upload and initial user record update."""

from __future__ import annotations

import os
from typing import Iterable

from core.database.db_manager import DatabaseManager
from core.database.models import User

TARGET_ROLE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Software Engineer", "Software Engineer"),
    ("Backend Engineer", "Backend Engineer"),
    ("Backend Developer", "Backend Developer"),
    ("Frontend Engineer", "Frontend Engineer"),
    ("Frontend Developer", "Frontend Developer"),
    ("Full Stack Engineer", "Full Stack Engineer"),
    ("Full Stack Developer", "Full Stack Developer"),
    ("Web Developer", "Web Developer"),
    ("Mobile App Developer", "Mobile App Developer"),
    ("Android Developer", "Android Developer"),
    ("iOS Developer", "iOS Developer"),
    ("Python Developer", "Python Developer"),
    ("Java Developer", "Java Developer"),
    ("JavaScript Developer", "JavaScript Developer"),
    ("TypeScript Developer", "TypeScript Developer"),
    ("React Developer", "React Developer"),
    ("Angular Developer", "Angular Developer"),
    ("Vue.js Developer", "Vue.js Developer"),
    ("Node.js Developer", "Node.js Developer"),
    ("Django Developer", "Django Developer"),
    ("Flask Developer", "Flask Developer"),
    ("API Developer", "API Developer"),
    ("Database Developer", "Database Developer"),
    ("SQL Developer", "SQL Developer"),
    ("PostgreSQL Developer", "PostgreSQL Developer"),
    ("Data Engineer", "Data Engineer"),
    ("AI Engineer", "AI Engineer"),
    ("Machine Learning Engineer", "Machine Learning Engineer"),
    ("Data Scientist", "Data Scientist"),
    ("Data Analyst", "Data Analyst"),
    ("Business Analyst", "Business Analyst"),
    ("Power BI Developer", "Power BI Developer"),
    ("BI Developer", "BI Developer"),
    ("Analytics Engineer", "Analytics Engineer"),
    ("NLP Engineer", "NLP Engineer"),
    ("MLOps Engineer", "MLOps Engineer"),
    ("Cloud Engineer", "Cloud Engineer"),
    ("DevOps Engineer", "DevOps Engineer"),
    ("Site Reliability Engineer", "Site Reliability Engineer"),
    ("Platform Engineer", "Platform Engineer"),
    ("QA Engineer", "QA Engineer"),
    ("Automation Test Engineer", "Automation Test Engineer"),
    ("Cybersecurity Engineer", "Cybersecurity Engineer"),
    ("Solutions Architect", "Solutions Architect"),
)

TARGET_ROLE_VALUES: set[str] = {value for value, _ in TARGET_ROLE_CHOICES}


class ResumeUploader:
    """Saves a resume to the filesystem and records its path on the User model.

    This class is responsible only for validating and persisting the file
    reference.  Parsing and skill extraction are handled by separate classes.
    """

    SUPPORTED_EXTENSIONS: tuple[str, ...] = (".pdf",)

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        """Initialize the uploader with an optional DatabaseManager instance.

        Args:
            db_manager: A DatabaseManager instance to use for database access.
                        If not provided, a new instance is created.
        """

        self._db = db_manager or DatabaseManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_resume(self, user_id: int, file_path: str) -> str:
        """Validate a resume file and record its path on the User record.

        Args:
            user_id: The primary key of the User who owns this resume.
            file_path: Absolute or relative path to the uploaded resume file.

        Returns:
            The normalized absolute file path that was stored.

        Raises:
            FileNotFoundError: If the file does not exist at the given path.
            ValueError: If the file format is not supported.
            User.DoesNotExist: If no User with the given user_id is found.
        """

        self.validate_resume_format(file_path)

        absolute_path = os.path.abspath(file_path)

        if not os.path.isfile(absolute_path):
            raise FileNotFoundError(
                f"Resume file not found: {absolute_path}"
            )

        user: User = User.objects.get(pk=user_id)
        user.resume_path = absolute_path
        user.save(update_fields=["resume_path"])

        return absolute_path

    def validate_resume_format(self, file_path: str) -> bool:
        """Check that the file extension is a supported resume format.

        Args:
            file_path: Path to the resume file.

        Returns:
            True when the format is valid.

        Raises:
            ValueError: If the extension is not in SUPPORTED_EXTENSIONS.
        """

        _, ext = os.path.splitext(file_path)
        if ext.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported resume format '{ext}'. "
                f"Supported formats: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )
        return True

    @staticmethod
    def validate_target_roles(target_roles: Iterable[str]) -> list[str]:
        """Validate and normalize selected target roles.

        Args:
            target_roles: Roles submitted by the user.

        Returns:
            A deduplicated list of validated role names preserving order.

        Raises:
            ValueError: If any submitted role is not part of the allowed set.
        """

        normalized_roles: list[str] = []
        for raw_role in target_roles:
            role = str(raw_role).strip()
            if not role:
                continue
            if role not in TARGET_ROLE_VALUES:
                raise ValueError(f"Unsupported target role: {role}")
            if role not in normalized_roles:
                normalized_roles.append(role)
        return normalized_roles
