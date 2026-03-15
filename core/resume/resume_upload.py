"""Handles resume file upload and initial user record update."""

from __future__ import annotations

import os

from core.database.db_manager import DatabaseManager
from core.database.models import User


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
