"""Deterministic per-user job relevance scoring and filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9+#.]+")
_EXPERIENCE_RE = re.compile(r"(\d{1,2})(?:\s*\+)?\s*(?:years|year|yrs|yr)", re.IGNORECASE)

_RELATED_SKILL_GROUPS: tuple[set[str], ...] = (
    {"python", "django", "flask", "fastapi"},
    {"javascript", "typescript", "node", "react", "vue", "angular"},
    {"aws", "gcp", "azure", "cloud"},
    {"postgres", "postgresql", "mysql", "sql", "sqlite"},
    {"docker", "kubernetes", "k8s", "devops"},
)


@dataclass(frozen=True)
class RelevanceConfig:
    """Runtime scoring configuration."""

    scale: int = 10
    threshold: float = 6.0


class UserJobRelevanceScorer:
    """Compute deterministic relevance and SAVE/DISCARD decisions per user."""

    def __init__(
        self,
        user_profile: dict[str, Any],
        scale: int = 10,
        threshold: float | None = None,
    ) -> None:
        if scale not in {5, 10}:
            raise ValueError("scale must be either 5 or 10")

        resolved_threshold = threshold
        if resolved_threshold is None:
            resolved_threshold = 3.0 if scale == 5 else 6.0

        self._config = RelevanceConfig(scale=scale, threshold=float(resolved_threshold))

        self._user_skills = _normalize_list(user_profile.get("skills") or [])
        self._user_skill_tokens = {skill: _tokenize(skill) for skill in self._user_skills}

        self._preferred_roles = _normalize_list(user_profile.get("preferred_roles") or [])
        self._preferred_location = _normalize_text(str(user_profile.get("location") or ""))

        self._user_experience_years = _safe_float(user_profile.get("experience"), default=0.0)

    def evaluate(self, job_data: dict[str, Any]) -> dict[str, Any]:
        """Return deterministic score output and SAVE/DISCARD decision."""

        job_title = str(job_data.get("title") or "")
        job_description = str(job_data.get("description") or "")
        job_location = _normalize_text(str(job_data.get("location") or ""))

        required_skills = _normalize_list(job_data.get("required_skills") or [])
        if not required_skills:
            required_skills = _infer_skills_from_text(f"{job_title} {job_description}")

        matched_skills, partial_matches, missing_skills = self._match_skills(required_skills)

        skill_score = self._compute_skill_score(
            required_skills=required_skills,
            exact_count=len(matched_skills),
            partial_count=partial_matches,
            missing_skills=missing_skills,
        )

        title_score = self._compute_title_score(job_title, job_description)
        experience_score = self._compute_experience_score(job_data, job_title, job_description)
        location_score = self._compute_location_score(job_location)

        weighted = (
            (skill_score * 0.65)
            + (title_score * 0.15)
            + (experience_score * 0.15)
            + (location_score * 0.05)
        )

        threshold = self._config.threshold
        score = round(1.0 + (weighted * (self._config.scale - 1.0)), 2)

        # Never allow high scores without strong skill evidence.
        if skill_score < 0.5:
            score = min(score, threshold)

        decision = "SAVE" if score > threshold else "DISCARD"

        return {
            "score": score,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "decision": decision,
        }

    def _match_skills(self, required_skills: list[str]) -> tuple[list[str], int, list[str]]:
        if not required_skills:
            return ([], 0, [])

        user_skill_set = set(self._user_skills)
        matched_skills: list[str] = []
        missing_skills: list[str] = []
        partial_count = 0

        for req in required_skills:
            if req in user_skill_set:
                matched_skills.append(req)
                continue

            if self._has_partial_or_related_match(req):
                partial_count += 1
            else:
                missing_skills.append(req)

        return (matched_skills, partial_count, missing_skills)

    def _has_partial_or_related_match(self, required_skill: str) -> bool:
        req_tokens = _tokenize(required_skill)
        if not req_tokens:
            return False

        for skill, tokens in self._user_skill_tokens.items():
            if not tokens:
                continue
            if req_tokens & tokens:
                return True
            if _are_related(skill, required_skill):
                return True

        return False

    @staticmethod
    def _compute_skill_score(
        required_skills: list[str],
        exact_count: int,
        partial_count: int,
        missing_skills: list[str],
    ) -> float:
        if not required_skills:
            return 0.4

        total = max(len(required_skills), 1)
        exact_ratio = exact_count / total
        partial_ratio = partial_count / total

        critical_missing = len(missing_skills[: min(3, total)])
        critical_penalty = (critical_missing / max(min(3, total), 1)) * 0.45

        score = (exact_ratio * 1.0) + (partial_ratio * 0.55) - critical_penalty
        return max(0.0, min(score, 1.0))

    def _compute_title_score(self, title: str, description: str) -> float:
        if not self._preferred_roles:
            return 0.0

        text = _normalize_text(f"{title} {description}")
        if not text:
            return 0.0

        exact_hits = sum(1 for role in self._preferred_roles if role in text)
        if exact_hits:
            return min(1.0, exact_hits / max(len(self._preferred_roles), 1))

        role_tokens = [_tokenize(role_str) for role_str in self._preferred_roles]
        text_tokens = _tokenize(text)
        fuzzy_hits = sum(1 for tokens in role_tokens if tokens and tokens & text_tokens)
        return min(0.6, fuzzy_hits / max(len(self._preferred_roles), 1))

    def _compute_experience_score(
        self,
        job_data: dict[str, Any],
        title: str,
        description: str,
    ) -> float:
        required = _safe_float(job_data.get("experience_required"), default=-1.0)
        if required < 0:
            required = _extract_experience_years(f"{title} {description}")

        if required < 0:
            return 0.5

        diff = self._user_experience_years - required
        if abs(diff) <= 1.0:
            return 1.0
        if abs(diff) <= 3.0:
            return 0.7
        return 0.4

    def _compute_location_score(self, job_location: str) -> float:
        if not self._preferred_location:
            return 0.5
        if not job_location:
            return 0.4
        if self._preferred_location in job_location or job_location in self._preferred_location:
            return 1.0
        if "remote" in job_location and "remote" in self._preferred_location:
            return 1.0
        return 0.3


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _normalize_list(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _normalize_text(str(value))
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)

    return result


def _tokenize(value: str) -> set[str]:
    normalized = _normalize_text(value)
    return set(_WORD_RE.findall(normalized))


def _extract_experience_years(text: str) -> float:
    match = _EXPERIENCE_RE.search(text)
    if not match:
        return -1.0
    try:
        return float(match.group(1))
    except ValueError:
        return -1.0


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _infer_skills_from_text(text: str) -> list[str]:
    skill_keywords = [
        "python",
        "django",
        "flask",
        "fastapi",
        "javascript",
        "typescript",
        "react",
        "node",
        "sql",
        "aws",
        "docker",
        "kubernetes",
        "java",
        "go",
        "ruby",
        "php",
    ]
    normalized = _normalize_text(text)
    return [skill for skill in skill_keywords if skill in normalized]


def _are_related(skill_a: str, skill_b: str) -> bool:
    a = _normalize_text(skill_a)
    b = _normalize_text(skill_b)
    if a == b:
        return True

    for group in _RELATED_SKILL_GROUPS:
        if a in group and b in group:
            return True

    return False
