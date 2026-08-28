from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from faculty_job_scout.dedupe import normalize_text
from faculty_job_scout.models import JobPosting

AP_TERMS = (
    "assistant professor",
    "tenure track assistant professor",
    "tenure-track assistant professor",
    "ttap",
)
FELLOWSHIP_TERMS = ("faculty fellowship", "faculty fellow", "presidential fellow")
TEACHING_ONLY_TERMS = (
    "teaching professor",
    "teaching track",
    "lecturer in teaching",
    "lecturer in discipline",
    "senior lecturer in discipline",
    "stipendiary lecturer",
    "visiting assistant professor",
)
LECTURER_TERMS = ("lecturer", "senior lecturer", "lectureship")
POSTDOC_TERMS = ("postdoc", "post-doctoral", "postdoctoral researcher", "research associate")
OPEN_RANK_TERMS = (
    "open rank",
    "assistant associate full professor",
    "associate full professor",
    "faculty positions",
)
UK_LECTURER_TERMS = LECTURER_TERMS
ASSOCIATE_TERMS = ("associate professor", "assistant/associate professor")
PART_TIME_TERMS = ("part time", "part-time")


@dataclass(frozen=True)
class RuleScore:
    fit_category: str
    fit_score: int
    role_type: str
    reasons: list[str]
    warnings: list[str]
    rule_score: float


def classify_role_type(title: str, description: str = "", region: str = "") -> str:
    text = normalize_text(f"{title} {description}")
    region_text = normalize_text(region)
    if any(term in text for term in POSTDOC_TERMS):
        if "fellow" in text and any(term in text for term in ("prestigious", "faculty", "tenure")):
            return "prestigious_postdoc_fellowship"
        return "regular_postdoc"
    if any(term in text for term in TEACHING_ONLY_TERMS):
        return "teaching_only"
    if any(term in text for term in LECTURER_TERMS) and region_text in {"us", "usa", "canada"}:
        return "teaching_only"
    if any(term in text for term in AP_TERMS):
        return "tenure_track_assistant_professor" if "tenure" in text else "assistant_professor"
    if any(term in text for term in UK_LECTURER_TERMS) and region_text in {"uk", "eu", "europe"}:
        return "lecturer_ap_equivalent"
    if any(term in text for term in FELLOWSHIP_TERMS):
        return "faculty_fellowship"
    if any(term in text for term in OPEN_RANK_TERMS):
        return "open_rank"
    if any(term in text for term in ASSOCIATE_TERMS) and region_text in {
        "eu",
        "europe",
        "sweden",
        "netherlands",
        "nordics",
    }:
        return "associate_professor_eu_tt_equivalent"
    return "other"


def score_job(
    job: JobPosting,
    keywords: dict[str, list[str]],
    institutions: dict[str, Any],
    settings: dict[str, Any],
) -> RuleScore:
    text = normalize_text(f"{job.searchable_text} {job.source_name}")
    role_type = classify_role_type(job.title, job.description_text, job.region)
    scoring = settings.get("scoring", {})
    score = 0.0
    reasons: list[str] = []
    warnings: list[str] = []

    role_weights = scoring.get("role_weights", {})
    role_weight = float(role_weights.get(role_type, role_weights.get("other", -0.25)))
    score += role_weight
    if role_weight >= 0:
        reasons.append(f"Role type is {role_type}.")
    else:
        warnings.append(f"Role type has a negative configured weight: {role_type}.")

    high_hits = _keyword_hits(text, keywords.get("high_value", []))
    medium_hits = _keyword_hits(text, keywords.get("medium_value", []))
    negative_hits = _keyword_hits(text, keywords.get("negative", []))
    if high_hits:
        score += min(
            float(scoring.get("max_high_value_bonus", 0.35)),
            float(scoring.get("high_value_per_hit", 0.06)) * len(high_hits),
        )
        reasons.append("High-value keywords: " + ", ".join(high_hits[:6]) + ".")
    if medium_hits:
        score += min(
            float(scoring.get("max_medium_value_bonus", 0.18)),
            float(scoring.get("medium_value_per_hit", 0.035)) * len(medium_hits),
        )
        reasons.append("Related keywords: " + ", ".join(medium_hits[:6]) + ".")
    if "tenure" in text:
        score += float(scoring.get("tenure_bonus", 0.06))
        reasons.append("Tenure-track language detected.")
    if _is_priority_institution(job.institution, institutions):
        score += float(scoring.get("priority_institution_bonus", 0.10))
        reasons.append("Institution is on the priority watchlist.")
    if _region_allowed(job.region, settings):
        score += float(scoring.get("included_region_bonus", 0.08))
        reasons.append("Region is included by default.")
    else:
        score -= float(scoring.get("excluded_region_penalty", 0.25))
        warnings.append(f"Region is excluded or not configured: {job.region or 'unknown'}.")
    if negative_hits:
        score -= min(
            float(scoring.get("max_negative_penalty", 0.35)),
            float(scoring.get("negative_per_hit", 0.10)) * len(negative_hits),
        )
        warnings.append("Negative keywords: " + ", ".join(negative_hits[:6]) + ".")
    if _is_part_time(text):
        score -= float(scoring.get("part_time_penalty", 0.25))
        warnings.append("Part-time role is lower priority.")
    if _is_expired(job.deadline):
        score -= 0.30
        warnings.append("Deadline appears to have passed.")

    score = max(0.0, min(1.0, score))
    fit_score = round(score * 100)
    if _is_part_time(text):
        fit_score = min(fit_score, int(scoring.get("lower_priority_score_cap", 54)))
    fit_category = _category_for_score(fit_score)
    return RuleScore(fit_category, fit_score, role_type, reasons, warnings, score)


def _keyword_hits(text: str, terms: list[str]) -> list[str]:
    hits = []
    for term in terms:
        normalized = normalize_text(term)
        if normalized and normalized in text:
            hits.append(term)
    return hits


def _category_for_score(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def _is_priority_institution(institution: str, institutions: dict[str, Any]) -> bool:
    normalized = normalize_text(institution)
    for entry in institutions.get("priority_universities", []):
        names = [entry.get("name", ""), *entry.get("aliases", [])]
        if any(normalize_text(name) == normalized for name in names):
            return True
    return False


def _region_allowed(region: str, settings: dict[str, Any]) -> bool:
    include = settings.get("regions", {}).get("include", {})
    normalized = normalize_text(region).replace(" ", "_")
    return bool(include.get(normalized, False))


def _is_expired(deadline: str | None) -> bool:
    if not deadline:
        return False
    try:
        return date.fromisoformat(deadline) < date.today()
    except ValueError:
        return False


def is_lower_priority_job(job: JobPosting) -> bool:
    text = normalize_text(f"{job.searchable_text} {job.source_name}")
    return _is_part_time(text)


def _is_part_time(text: str) -> bool:
    return any(normalize_text(term) in text for term in PART_TIME_TERMS)
