"""Generates a reusable freelance proposal template from resume data."""

from __future__ import annotations

import logging
from typing import List

import openai

from core.config.constants import DEFAULT_PROPOSAL_LENGTH
from core.config.settings import OPENAI_API_KEY, OPENAI_MODEL_NAME
from core.database.db_manager import DatabaseManager
from core.database.models import ProposalTemplate, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style anchor
# ---------------------------------------------------------------------------
# LLMs trained on marketing copy tend to produce bullet-heavy, over-polished
# text that reads as AI-generated.  Providing a concrete human-written example
# inside the prompt (a "style anchor") gives the model a direct target to aim
# for and consistently reduces formal / robotic phrasing.
_STYLE_ANCHOR_EXAMPLE = """\
Hi,

I'm a full stack developer with solid experience in Python and Django. I've \
spent the last few years building backend systems and APIs, and I enjoy working \
on projects where clean architecture and reliability matter.

Your project sounds interesting and closely related to the kind of work I \
usually take on. I'd be happy to learn more about what you're building and see \
how I can help.

Best regards"""


def build_proposal_prompt(summary: str, skills: List[str]) -> str:
    """Construct a structured four-section prompt for proposal template generation.

    The prompt is divided into four sections to give the model clear, separated
    instructions and to reduce AI-like writing patterns:

    * **Section 1** supplies the developer's resume details so the model has
      accurate content to draw from.
    * **Section 2** lists strict writing rules that suppress typical AI
      formatting artefacts (bullets, markdown symbols, corporate jargon).
    * **Section 3** provides a human-written style anchor example.  Research
      and practice show that giving the model a concrete sample of the target
      style produces more natural, readable output than rule-only prompts.
    * **Section 4** states the final task with output requirements.

    Args:
        summary: The candidate's experience summary extracted from their resume.
        skills: A list of skill name strings to mention in the proposal.

    Returns:
        A fully assembled prompt string ready to be sent to the OpenAI API.
    """

    skills_formatted = ", ".join(skills) if skills else "various technologies"

    return f"""\
SECTION 1 — RESUME INFORMATION

Summary:
{summary}

Key skills: {skills_formatted}

---

SECTION 2 — WRITING RULES

Follow these rules strictly when writing the proposal:
- Use simple, natural English that a real developer would write.
- Avoid corporate or marketing jargon.
- Do NOT use bullet points.
- Do NOT use symbols like *, **, --, or any markdown formatting.
- Do NOT structure the text as a list.
- Use short, natural paragraphs.
- Keep the tone friendly and conversational.
- Avoid robotic or overly polished sentences.
- Output plain text only — no headings, no formatting marks.

---

SECTION 3 — STYLE ANCHOR EXAMPLE

The example below shows the correct tone and writing style.
Write the proposal in the same tone and writing style as the example below.
Do not copy the sentences. Only mimic the writing style.

Example proposal style:

{_STYLE_ANCHOR_EXAMPLE}

---

SECTION 4 — TASK

Using the resume information in Section 1, write a reusable freelance proposal
template of approximately {DEFAULT_PROPOSAL_LENGTH} characters. The template must:
- Open with a natural greeting.
- Introduce the developer briefly and mention their main area of work.
- Mention a few key skills naturally inside the sentences (no listing).
- Close with a friendly, open-ended offer to help.
- Sound like a real developer wrote it, not a writing assistant.
- Contain no placeholder brackets and no job-specific content.

Return only the proposal text."""


class ProposalTemplateGenerator:
    """Generates and persists a reusable proposal template for a freelancer.

    Single responsibility: given a user's stored resume summary and skills,
    produce a general-purpose proposal text via OpenAI and save it.
    """

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        openai_client: openai.OpenAI | None = None,
    ) -> None:
        """Initialise with optional dependency injection for testability.

        Args:
            db_manager: A DatabaseManager instance for database access.
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

    def generate_template(self, user_id: int) -> str:
        """Fetch resume data, generate a proposal template, and persist it.

        Args:
            user_id: The primary key of the User for whom to generate a
                     template.

        Returns:
            The generated proposal template text that was stored.

        Raises:
            User.DoesNotExist: If no User with the given user_id is found.
            ValueError: If no resume summary is found for the user, or the
                        OpenAI response is empty.
            openai.OpenAIError: Propagated from the OpenAI client on API errors.
        """

        user: User = User.objects.get(pk=user_id)

        summary, skills_list = self._fetch_profile(user_id)

        template_text = self._call_openai(summary, skills_list)

        if not template_text.strip():
            raise ValueError(
                f"OpenAI returned an empty proposal template for user {user_id}."
            )

        ProposalTemplate.objects.create(
            user=user,
            template_text=template_text,
        )

        logger.info(
            "Saved new proposal template for user %s (%d chars).",
            user_id,
            len(template_text),
        )

        return template_text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_profile(self, user_id: int) -> tuple[str, list[str]]:
        """Retrieve the latest resume summary and skill names for a user.

        Args:
            user_id: The primary key of the target User.

        Returns:
            A 2-tuple of (summary string, list of skill name strings).

        Raises:
            ValueError: If no resume data has been stored for this user.
        """

        from core.database.models import ResumeData  # noqa: PLC0415

        latest_resume = (
            ResumeData.objects.filter(user_id=user_id)
            .order_by("-created_at")
            .first()
        )

        if not latest_resume:
            raise ValueError(
                f"No resume data found for user {user_id}. "
                "Run skill extraction before generating a proposal template."
            )

        skills_qs = self._db.get_user_skills(user_id)
        skill_names = list(skills_qs.values_list("skill_name", flat=True))

        return latest_resume.summary, skill_names

    def _call_openai(self, summary: str, skills: list[str]) -> str:
        """Build the structured prompt and send it to the OpenAI chat API.

        Uses ``build_proposal_prompt`` to assemble a four-section prompt that
        includes resume data, writing rules, a human-written style anchor, and
        the final task description.  The style anchor reduces AI-like phrasing
        by giving the model a concrete example to match in tone.

        Args:
            summary: The candidate's experience summary.
            skills: A list of skill name strings.

        Returns:
            The raw proposal template text returned by the model.
        """

        prompt = build_proposal_prompt(summary, skills)

        response = self._client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        return (response.choices[0].message.content or "").strip()


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
            "Add it to your environment variables before using "
            "ProposalTemplateGenerator."
        )
    return openai.OpenAI(api_key=OPENAI_API_KEY)
