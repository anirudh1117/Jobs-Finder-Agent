"""Extracts skills and an experience summary from resume text using OpenAI."""

from __future__ import annotations

import json
import logging
from typing import Any

import openai

from core.config.settings import OPENAI_API_KEY, OPENAI_MODEL_NAME
from core.database.db_manager import DatabaseManager
from core.database.models import ResumeData, Skill, User

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a resume analysis assistant. Given the resume text below, extract:
1. A list of distinct technical skills (programming languages, frameworks, tools).
2. A concise professional experience summary (3-5 sentences).
3. A list of notable technologies that form the candidate's primary tech stack.

Return ONLY valid JSON in this exact shape – no markdown fences, no extra keys:
{{
  "skills": ["skill1", "skill2", ...],
  "summary": "...",
  "tech_stack": ["tech1", "tech2", ...]
}}

Resume text:
---
{resume_text}
---
"""


class SkillExtractor:
    """Sends resume text to OpenAI and persists the extracted skills and summary.

    Single responsibility: translate raw resume text into structured profile
    data and store it via the DatabaseManager.
    """

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        openai_client: openai.OpenAI | None = None,
    ) -> None:
        """Initialise with optional dependency injection for testability.

        Args:
            db_manager: A DatabaseManager instance for database writes.
                        A new instance is created when not provided.
            openai_client: An openai.OpenAI client instance.
                           A new instance (reading OPENAI_API_KEY from the
                           environment) is created when not provided.
        """

        self._db = db_manager or DatabaseManager()
        self._client = openai_client or _build_openai_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_skills_and_summary(
        self,
        user_id: int,
        resume_text: str,
    ) -> dict[str, Any]:
        """Extract skills and summary from resume text and persist the results.

        Args:
            user_id: The primary key of the User who owns this resume.
            resume_text: The cleaned plain-text content of the resume.

        Returns:
            A dict with keys ``skills`` (list[str]), ``summary`` (str), and
            ``tech_stack`` (list[str]) as returned by the model.

        Raises:
            User.DoesNotExist: If no User with the given user_id is found.
            ValueError: If the model response cannot be parsed as valid JSON or
                        is missing required keys.
            openai.OpenAIError: Propagated from the OpenAI client on API errors.
        """

        user: User = User.objects.get(pk=user_id)

        raw_response = self._call_openai(resume_text)
        extracted = self._parse_response(raw_response)

        self._save_skills(user, extracted.get("skills", []))
        self._save_resume_data(user, extracted.get("summary", ""), resume_text)

        return extracted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_openai(self, resume_text: str) -> str:
        """Send the extraction prompt to the OpenAI chat API.

        Args:
            resume_text: Plain-text resume content to analyse.

        Returns:
            The raw string content of the model's first message.
        """

        prompt = _EXTRACTION_PROMPT.format(resume_text=resume_text)
        response = self._client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        """Parse the JSON extraction result from the model response.

        Args:
            raw: The raw string content returned by the model.

        Returns:
            A dict containing ``skills``, ``summary``, and ``tech_stack``.

        Raises:
            ValueError: If the content is not valid JSON or required keys are
                        missing.
        """

        # Strip accidental markdown fences the model may add.
        stripped = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

        try:
            data: dict[str, Any] = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"OpenAI returned non-JSON content during skill extraction: {exc}\n"
                f"Raw response: {raw[:500]}"
            ) from exc

        for required_key in ("skills", "summary", "tech_stack"):
            if required_key not in data:
                raise ValueError(
                    f"OpenAI response is missing required key '{required_key}'. "
                    f"Received keys: {list(data.keys())}"
                )

        return data

    def _save_skills(self, user: User, skills: list[str]) -> None:
        """Persist extracted skills for the user, skipping duplicates.

        Existing skills for the user are preserved; only new skill names are
        inserted so that repeated extraction runs are idempotent.

        Args:
            user: The User instance to associate the skills with.
            skills: A list of skill name strings.
        """

        existing_names = set(
            Skill.objects.filter(user=user).values_list("skill_name", flat=True)
        )

        new_skills = [
            Skill(user=user, skill_name=name.strip())
            for name in skills
            if name.strip() and name.strip() not in existing_names
        ]

        if new_skills:
            Skill.objects.bulk_create(new_skills)
            logger.info(
                "Saved %d new skills for user %s.", len(new_skills), user.pk
            )

    def _save_resume_data(
        self,
        user: User,
        summary: str,
        extracted_text: str,
    ) -> None:
        """Create a new ResumeData record for the user.

        Args:
            user: The User instance to associate the record with.
            summary: The AI-generated experience summary.
            extracted_text: The full plain-text content of the resume.
        """

        ResumeData.objects.create(
            user=user,
            summary=summary,
            extracted_text=extracted_text,
        )
        logger.info("Saved resume data for user %s.", user.pk)


# ------------------------------------------------------------------
# Module-level helper
# ------------------------------------------------------------------

def _build_openai_client() -> openai.OpenAI:
    """Construct an OpenAI client from the configured API key.

    Raises:
        ValueError: If OPENAI_API_KEY is not set in the environment.
    """

    if not OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY is not set. "
            "Add it to your environment variables before using SkillExtractor."
        )
    return openai.OpenAI(api_key=OPENAI_API_KEY)
