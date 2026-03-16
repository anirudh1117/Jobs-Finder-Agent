"""Generates personalized freelance proposals using OpenAI."""

from __future__ import annotations

import traceback
from typing import Any

import openai

from core.config.constants import DEFAULT_PROPOSAL_LENGTH
from core.config.settings import OPENAI_API_KEY, OPENAI_MODEL_NAME
from core.logging.system_logger import log_event
from core.proposal.proposal_optimizer import ProposalOptimizer

_STYLE_ANCHOR_EXAMPLE = """Hi,

I'm a full stack developer with solid experience in Python and Django. I've spent the last few years building backend systems and APIs, and I enjoy working on projects where clean architecture and reliability matter.

Your project sounds interesting and closely related to the kind of work I usually take on. I'd be happy to learn more about what you're building and see how I can help.

Best regards"""


class ProposalGenerator:
    """Builds prompts and generates proposal text through OpenAI.

    This class is responsible only for generation and does not perform database
    reads or writes directly.
    """

    def __init__(
        self,
        openai_client: openai.OpenAI | None = None,
        optimizer: ProposalOptimizer | None = None,
    ) -> None:
        """Initialize generation dependencies.

        Args:
            openai_client: Optional OpenAI client for dependency injection.
            optimizer: Optional optimizer to enforce plain-text cleanup.
        """

        self._client = openai_client or _build_openai_client()
        self._optimizer = optimizer or ProposalOptimizer()

    def generate_proposal(
        self,
        user_context: dict[str, Any],
        job_context: dict[str, Any],
    ) -> str:
        """Generate a plain-text freelance proposal.

        Args:
            user_context: Dictionary containing summary, skills, and template.
            job_context: Dictionary containing title, description, platform,
                budget, and hourly_rate.

        Returns:
            Generated proposal as plain text.

        Raises:
            ValueError: If the model returns an empty response.
        """

        prompt = self._build_prompt(user_context=user_context, job_context=job_context)

        payload = {
            "model": OPENAI_MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.35,
        }
        platform = str(job_context.get("platform", "")).strip() or None
        job_url = str(job_context.get("job_url", "")).strip() or None
        log_event(
            level="INFO",
            module="openai",
            action="openai_request",
            message="Sending proposal generation request",
            status="SUCCESS",
            platform=platform,
            job_url=job_url,
            request_payload=payload,
        )

        try:
            response = self._client.chat.completions.create(**payload)
        except Exception:  # noqa: BLE001
            log_event(
                level="ERROR",
                module="openai",
                action="openai_response",
                message="OpenAI API failed",
                status="FAILED",
                platform=platform,
                job_url=job_url,
                request_payload=payload,
                stack_trace=traceback.format_exc(),
            )
            raise

        log_event(
            level="INFO",
            module="openai",
            action="openai_response",
            message="Received proposal generation response",
            status="SUCCESS",
            platform=platform,
            job_url=job_url,
            request_payload=payload,
            response_payload=response.model_dump() if hasattr(response, "model_dump") else None,
        )
        content = (response.choices[0].message.content or "").strip()

        if not content:
            raise ValueError("OpenAI returned an empty proposal.")

        return self._optimizer.optimize_proposal(content)

    def _build_prompt(
        self,
        user_context: dict[str, Any],
        job_context: dict[str, Any],
    ) -> str:
        """Build the full structured prompt required for proposal generation."""

        summary = str(user_context.get("summary", "")).strip()
        skills = user_context.get("skills", []) or []
        template = str(user_context.get("template", "")).strip()

        title = str(job_context.get("title", "")).strip()
        description = str(job_context.get("description", "")).strip()
        budget = float(job_context.get("budget", 0.0) or 0.0)
        hourly_rate = float(job_context.get("hourly_rate", 0.0) or 0.0)

        skills_text = ", ".join(str(skill).strip() for skill in skills if str(skill).strip())
        if not skills_text:
            skills_text = "Not specified"

        template_text = template if template else "No saved template available."

        pricing_text = (
            f"Budget: ${budget:.2f}; Hourly rate: ${hourly_rate:.2f}"
            if budget > 0 or hourly_rate > 0
            else "Budget and hourly rate are not specified."
        )

        return f"""SECTION 1 - User context
Resume summary:
{summary}

Skills:
{skills_text}

Stored proposal template:
{template_text}

SECTION 2 - Writing rules
Use simple natural English.
Avoid corporate jargon.
Do not use bullet points.
Do not use symbols like *, **, --.
Do not produce lists.
Use normal paragraphs.
Avoid robotic tone.
Output plain text only.

SECTION 3 - Style anchor example
Example proposal style:

{_STYLE_ANCHOR_EXAMPLE}

Write the proposal in the same tone and writing style as the example above. Do not copy the sentences. Only mimic the writing style.

SECTION 4 - Job information
Job title: {title}
Job description:
{description}

{pricing_text}
Platform: {job_context.get("platform", "")}

SECTION 5 - Task
Write a concise reusable freelance proposal in plain text (around {DEFAULT_PROPOSAL_LENGTH} characters max).
The proposal must include a greeting, mention relevant skills naturally, refer to the project in a conversational way, and end with a friendly closing.
Return only the proposal text."""


def _build_openai_client() -> openai.OpenAI:
    """Create an OpenAI client using environment-backed credentials."""

    if not OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY is not set. Configure it in the environment before "
            "using ProposalGenerator."
        )
    return openai.OpenAI(api_key=OPENAI_API_KEY)
