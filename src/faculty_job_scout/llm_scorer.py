from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from faculty_job_scout.models import JobPosting

ALLOWED_CATEGORIES = {"A", "B", "C", "D"}


class RoleType(str, Enum):
    assistant_professor = "assistant_professor"
    tenure_track_assistant_professor = "tenure_track_assistant_professor"
    lecturer_ap_equivalent = "lecturer_ap_equivalent"
    faculty_fellowship = "faculty_fellowship"
    prestigious_postdoc_fellowship = "prestigious_postdoc_fellowship"
    regular_postdoc = "regular_postdoc"
    teaching_only = "teaching_only"
    open_rank = "open_rank"
    associate_professor_eu_tt_equivalent = "associate_professor_eu_tt_equivalent"
    business_school_adjacent = "business_school_adjacent"
    other = "other"


ALLOWED_ROLE_TYPES = {role.value for role in RoleType}

SYSTEM_PROMPT = """You assess academic job postings for one candidate.
Score only the supplied evidence. Do not reward university prestige and do not invent missing facts.
Use 0 for no fit or no evidence and 5 for an excellent direct fit.
Evidence must be short, specific, and grounded in the posting.
The application angle must connect the candidate's actual work to the advertised research agenda.
List required materials and deadlines only when explicitly stated.
Use the closest allowed role_type enum value. Map assistant-professor titles to
assistant_professor, UK/EU lecturer titles to lecturer_ap_equivalent, open-rank titles to
open_rank, and unclear or malformed pages to other.
Python applies configured policy penalties for part-time, expired, and excluded roles."""


class JobAssessment(BaseModel):
    research_topic_fit: int = Field(ge=0, le=5)
    methods_fit: int = Field(ge=0, le=5)
    career_stage_fit: int = Field(ge=0, le=5)
    department_fit: int = Field(ge=0, le=5)
    teaching_fit: int = Field(ge=0, le=5)
    role_type: RoleType
    summary: str
    evidence: list[str]
    application_angle: str
    required_materials: list[str]
    warnings: list[str]
    deadline: str | None
    confidence: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class LLMScore:
    fit_category: str
    fit_score: int
    role_type: str
    summary: str
    match_reasons: list[str]
    application_angle: str
    required_materials: list[str]
    warnings: list[str]
    deadline: str | None
    confidence: float


class LLMClient(Protocol):
    def score(self, job: JobPosting, profile: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenAIResponsesClient:
    def __init__(
        self,
        model: str = "gpt-5.6-luna",
        api_key_env_var: str = "OPENAI_API_KEY",
        sdk_client: Any | None = None,
    ) -> None:
        self.model = model
        self.last_usage: dict[str, int] = {}
        if sdk_client is not None:
            self.client = sdk_client
            return
        api_key = os.getenv(api_key_env_var)
        if not api_key:
            raise RuntimeError(f"{api_key_env_var} is not set")
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=60.0, max_retries=2)

    def score(self, job: JobPosting, profile: dict[str, Any]) -> dict[str, Any]:
        response = self.client.responses.parse(
            model=self.model,
            reasoning={"effort": "low"},
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _request_payload(job, profile)},
            ],
            text_format=JobAssessment,
        )
        assessment = response.output_parsed
        if assessment is None:
            raise RuntimeError("OpenAI returned no parsed job assessment")
        usage = getattr(response, "usage", None)
        if usage:
            self.last_usage = {
                "input_tokens": int(getattr(usage, "input_tokens", 0)),
                "output_tokens": int(getattr(usage, "output_tokens", 0)),
                "total_tokens": int(getattr(usage, "total_tokens", 0)),
            }
        return _assessment_payload(assessment)


class MockLLMClient:
    def score(self, job: JobPosting, profile: dict[str, Any]) -> dict[str, Any]:
        return {
            "fit_category": job.fit_category,
            "fit_score": job.fit_score,
            "role_type": job.role_type,
            "summary": job.summary
            or f"{job.title} at {job.institution} appears relevant based on rule scoring.",
            "match_reasons": job.match_reasons[:3]
            or ["Rule-based prescreen matched the profile."],
            "application_angle": job.application_angle,
            "required_materials": job.required_materials,
            "warnings": job.warnings,
            "deadline": job.deadline,
            "confidence": 0.70,
        }


def validate_llm_response(payload: dict[str, Any]) -> LLMScore:
    category = str(payload.get("fit_category", "")).strip()
    role_type = _normalize_role_type(payload.get("role_type", ""))
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Invalid fit_category: {category}")
    if role_type not in ALLOWED_ROLE_TYPES:
        raise ValueError(f"Invalid role_type: {role_type}")
    fit_score = int(payload.get("fit_score", 0))
    if not 0 <= fit_score <= 100:
        raise ValueError("fit_score must be between 0 and 100")
    confidence = float(payload.get("confidence", 0))
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return LLMScore(
        fit_category=category,
        fit_score=fit_score,
        role_type=role_type,
        summary=str(payload.get("summary", "")),
        match_reasons=list(payload.get("match_reasons") or []),
        application_angle=str(payload.get("application_angle", "")),
        required_materials=list(payload.get("required_materials") or []),
        warnings=list(payload.get("warnings") or []),
        deadline=payload.get("deadline"),
        confidence=confidence,
    )


def _normalize_role_type(value: object) -> str:
    if isinstance(value, RoleType):
        return value.value
    raw = str(value).strip()
    if raw in ALLOWED_ROLE_TYPES:
        return raw
    normalized = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    aliases = {
        "assistant professor": "assistant_professor",
        "lecturer or senior lecturer": "lecturer_ap_equivalent",
        "senior lecturer or lecturer": "lecturer_ap_equivalent",
        "non tenure open rank and title": "open_rank",
    }
    if normalized in aliases:
        return aliases[normalized]
    if "malformed" in normalized or normalized.startswith("unclear"):
        return "other"
    return raw


def apply_llm_score(job: JobPosting, score: LLMScore) -> JobPosting:
    job.fit_category = score.fit_category
    job.fit_score = score.fit_score
    job.role_type = score.role_type
    job.summary = score.summary
    job.match_reasons = score.match_reasons
    job.application_angle = score.application_angle
    job.required_materials = score.required_materials
    job.warnings = score.warnings
    if score.deadline:
        job.deadline = score.deadline
    return job


def score_with_llm(job: JobPosting, profile: dict[str, Any], client: LLMClient) -> JobPosting:
    score = validate_llm_response(client.score(job, profile))
    return apply_llm_score(job, score)


def _request_payload(job: JobPosting, profile: dict[str, Any]) -> str:
    payload = {
        "candidate_profile": profile,
        "rule_prescreen": {
            "score": job.fit_score,
            "role_type": job.role_type,
            "reasons": job.match_reasons,
            "warnings": job.warnings,
        },
        "job": {
            "title": job.title,
            "institution": job.institution,
            "department": job.department,
            "school": job.school,
            "location": job.location,
            "region": job.region,
            "description": job.description_text[:15_000],
            "deadline": job.deadline,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _assessment_payload(assessment: JobAssessment) -> dict[str, Any]:
    fit_score = (
        7 * assessment.research_topic_fit
        + 5 * assessment.methods_fit
        + 3 * assessment.career_stage_fit
        + 3 * assessment.department_fit
        + 2 * assessment.teaching_fit
    )
    if fit_score >= 75:
        category = "A"
    elif fit_score >= 55:
        category = "B"
    elif fit_score >= 35:
        category = "C"
    else:
        category = "D"
    return {
        "fit_category": category,
        "fit_score": fit_score,
        "role_type": assessment.role_type.value,
        "summary": assessment.summary,
        "match_reasons": assessment.evidence,
        "application_angle": assessment.application_angle,
        "required_materials": assessment.required_materials,
        "warnings": assessment.warnings,
        "deadline": assessment.deadline,
        "confidence": assessment.confidence,
    }
