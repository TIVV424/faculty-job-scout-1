from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class DuplicateMatch:
    canonical_id: str
    reason: str
    score: float


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.casefold()
    value = re.sub(r"https?://(www\.)?", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def build_canonical_id(title: str, institution: str, application_url: str = "") -> str:
    url_key = normalize_text(application_url)
    if url_key and "configure me" not in url_key:
        source = f"url:{url_key}"
    else:
        source = f"title-inst:{normalize_text(title)}::{normalize_text(institution)}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def similarity(left: str | None, right: str | None) -> float:
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def title_similarity(left: str | None, right: str | None) -> float:
    return similarity(_core_title(left), _core_title(right))


def find_duplicate(
    candidate: object,
    existing_jobs: list[object],
    fuzzy_title_threshold: float = 0.90,
    fuzzy_institution_threshold: float = 0.90,
) -> DuplicateMatch | None:
    candidate_url = normalize_text(getattr(candidate, "application_url", ""))
    for existing in existing_jobs:
        if getattr(existing, "canonical_id", "") == getattr(candidate, "canonical_id", ""):
            return DuplicateMatch(existing.canonical_id, "canonical_id", 1.0)
        existing_url = normalize_text(getattr(existing, "application_url", ""))
        if candidate_url and candidate_url == existing_url:
            return DuplicateMatch(existing.canonical_id, "application_url", 1.0)
        title_score = title_similarity(
            getattr(candidate, "title", ""),
            getattr(existing, "title", ""),
        )
        inst_score = similarity(
            getattr(candidate, "institution", ""),
            getattr(existing, "institution", ""),
        )
        if title_score >= fuzzy_title_threshold and inst_score >= fuzzy_institution_threshold:
            return DuplicateMatch(
                existing.canonical_id,
                "fuzzy_title_institution",
                min(title_score, inst_score),
            )
    return None


def _core_title(value: str | None) -> str:
    text = value or ""
    text = re.split(
        r"\b(?:Personal type|Field of expertise|Organisation|Organization|Apply no later than|"
        r"Apply before|Full-time equivalent|Salary|Read more)\s*:",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return text.strip(" -,:;")
