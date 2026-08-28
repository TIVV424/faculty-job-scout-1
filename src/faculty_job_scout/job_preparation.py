from __future__ import annotations

import re

from faculty_job_scout.dedupe import find_duplicate, normalize_text
from faculty_job_scout.models import JobPosting

MISSING_INSTITUTIONS = {
    "",
    "institution not provided",
    "unknown institution",
    "not listed",
}


def prepare_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    for job in jobs:
        enrich_job_metadata(job)
    return consolidate_jobs(jobs)


def enrich_job_metadata(job: JobPosting) -> JobPosting:
    text = f"{job.title}\n{job.description_text}"
    if not job.department and not job.school:
        unit = _extract_unit(text)
        if unit.lower().startswith("department"):
            job.department = unit
        elif unit:
            job.school = unit

    if is_missing_institution(job.institution):
        institution = _extract_institution(text)
        if institution:
            job.institution = institution
    return job


def consolidate_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    unique: list[JobPosting] = []
    by_canonical_id: dict[str, JobPosting] = {}
    by_url: dict[str, JobPosting] = {}
    by_institution: dict[str, list[JobPosting]] = {}
    for job in jobs:
        url_key = normalize_text(job.application_url)
        existing = by_canonical_id.get(job.canonical_id) or by_url.get(url_key)
        institution_key = _institution_key(job.institution)
        candidates = by_institution.get(institution_key, []) if institution_key else []
        match = find_duplicate(job, candidates) if not existing else None
        if not match:
            if not existing:
                unique.append(job)
                by_canonical_id[job.canonical_id] = job
                if url_key:
                    by_url[url_key] = job
                if institution_key:
                    by_institution.setdefault(institution_key, []).append(job)
                continue
        if not existing:
            existing = by_canonical_id[match.canonical_id]
        merge_job_postings(existing, job)
    return unique


def merge_job_postings(target: JobPosting, candidate: JobPosting) -> JobPosting:
    if _is_expanded_title(target.title, candidate.title):
        target.title = candidate.title
    if is_missing_institution(target.institution) and not is_missing_institution(
        candidate.institution
    ):
        target.institution = candidate.institution

    for field in (
        "department",
        "school",
        "location",
        "country",
        "region",
        "deadline",
        "date_posted",
        "summary",
        "application_angle",
    ):
        if not getattr(target, field) and getattr(candidate, field):
            setattr(target, field, getattr(candidate, field))

    if target.description_text.startswith("Candidate link extracted from") or len(
        candidate.description_text
    ) > len(target.description_text):
        target.description_text = candidate.description_text
    if candidate.fit_score > target.fit_score:
        for field in ("fit_category", "fit_score", "role_type", "summary", "application_angle"):
            setattr(target, field, getattr(candidate, field))

    for field in ("match_reasons", "required_materials", "warnings"):
        combined = list(dict.fromkeys([*getattr(target, field), *getattr(candidate, field)]))
        setattr(target, field, combined)
    target.is_priority_institution = target.is_priority_institution or candidate.is_priority_institution
    target.is_new_this_run = target.is_new_this_run or candidate.is_new_this_run
    return target


def is_missing_institution(value: str) -> bool:
    return value.strip().casefold() in MISSING_INSTITUTIONS


def _extract_unit(text: str) -> str:
    labeled = re.search(
        r"\b(?:Organisation|Organization|Department|School)\s*:\s*"
        r"(.+?)(?=\s+(?:Apply|Posted|Personal type|Field of expertise|Full[- ]time|Salary)\b|[.;\n]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if labeled:
        value = _clean(labeled.group(1))
        label = labeled.group(0).split(":", 1)[0].strip()
        if label.casefold() == "department" and not value.casefold().startswith("department"):
            return f"Department of {value}"
        if label.casefold() == "school" and not value.casefold().startswith("school"):
            return f"School of {value}"
        return value

    unit = re.search(
        r"\b((?:Department|School|College|Faculty) of .+?)"
        r"(?=\s+(?:at|within|invites|seeks|is seeking|Apply|Posted|Read more)\b|[.;\n]|$)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean(unit.group(1)) if unit else ""


def _extract_institution(text: str) -> str:
    labeled = re.search(
        r"\b(?:Institution|Employer|Hiring organization)\s*:\s*"
        r"(.+?)(?=\s+(?:Location|Department|School|Category|Posted|Type|Salary)\s*:|[.;\n]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if labeled:
        return _clean(labeled.group(1))

    patterns = (
        r"\bat\s+((?:the\s+)?University of (?:[A-Z][\w&'\u2019.-]*\s*){1,6})",
        r"\bat\s+((?:the\s+)?(?:[A-Z][\w&'\u2019.-]*\s+){1,7}University)",
        r"\bat\s+((?:the\s+)?(?:[A-Z][\w&'\u2019.-]*\s+){1,7}Institute of Technology)",
        r"-\s*((?:the\s+)?University of (?:[A-Z][\w&'\u2019.-]*\s*){1,6})$",
        r"-\s*((?:the\s+)?(?:[A-Z][\w&'\u2019.-]*\s+){1,7}University)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean(match.group(1))
    return ""


def _is_expanded_title(current: str, candidate: str) -> bool:
    current_text = current.casefold()
    candidate_text = candidate.casefold()
    return candidate_text in current_text and len(candidate) + 15 < len(current)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -,:;")


def _institution_key(value: str) -> str:
    if is_missing_institution(value):
        return ""
    return re.sub(r"^the\s+", "", normalize_text(value))
