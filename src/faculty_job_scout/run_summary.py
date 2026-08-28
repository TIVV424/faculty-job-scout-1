from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from faculty_job_scout.models import JobPosting
from faculty_job_scout.newsletter import Newsletter


@dataclass(frozen=True)
class TargetPositionCheck:
    name: str
    url: str
    title: str
    institution: str
    found: bool
    matched_job: JobPosting | None = None


def write_markdown_summary(
    *,
    run_jobs: list[JobPosting],
    saved_jobs: list[JobPosting],
    warnings: list[str],
    newsletter: Newsletter,
    target_positions: list[dict],
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_checks = check_target_positions(run_jobs, target_positions)
    path.write_text(
        _render_summary(
            run_jobs=run_jobs,
            saved_jobs=saved_jobs,
            warnings=warnings,
            newsletter=newsletter,
            target_checks=target_checks,
        ),
        encoding="utf-8",
    )
    return path


def check_target_positions(
    jobs: list[JobPosting], target_positions: list[dict]
) -> list[TargetPositionCheck]:
    checks: list[TargetPositionCheck] = []
    for target in target_positions:
        title = str(target.get("title") or "").strip()
        institution = str(target.get("institution") or "").strip()
        url = str(target.get("url") or "").strip()
        name = str(target.get("name") or title or url or "target position")
        matched = next(
            (
                job
                for job in jobs
                if _matches_target(job, title=title, institution=institution, url=url)
            ),
            None,
        )
        checks.append(
            TargetPositionCheck(
                name=name,
                url=url,
                title=title,
                institution=institution,
                found=matched is not None,
                matched_job=matched,
            )
        )
    return checks


def _matches_target(job: JobPosting, *, title: str, institution: str, url: str) -> bool:
    if url and any(
        _same_or_contained_url(url, candidate)
        for candidate in (job.application_url, job.source_url)
        if candidate
    ):
        return True
    return _title_matches(job.title, title) and _soft_contains(job.institution, institution)


def _same_or_contained_url(target_url: str, candidate_url: str) -> bool:
    target = _canonical_url(target_url)
    candidate = _canonical_url(candidate_url)
    return bool(target and candidate and (target == candidate or target in candidate))


def _canonical_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/").lower()
    return f"{parsed.netloc.lower()}{path}"


def _soft_contains(left: str, right: str) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    return bool(
        normalized_left
        and normalized_right
        and (normalized_left in normalized_right or normalized_right in normalized_left)
    )


def _title_matches(job_title: str, target_title: str) -> bool:
    target_terms = _important_terms(target_title)
    if not target_terms:
        return _soft_contains(job_title, target_title)
    job_terms = set(_tokens(job_title))
    return target_terms.issubset(job_terms)


def _important_terms(value: str) -> set[str]:
    stopwords = {
        "academic",
        "assistant",
        "associate",
        "full",
        "in",
        "of",
        "or",
        "position",
        "professor",
        "specialization",
        "tenure",
        "track",
        "with",
    }
    return {token for token in _tokens(value) if token not in stopwords}


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _render_summary(
    *,
    run_jobs: list[JobPosting],
    saved_jobs: list[JobPosting],
    warnings: list[str],
    newsletter: Newsletter,
    target_checks: list[TargetPositionCheck],
) -> str:
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "# Faculty Job Scout Local Summary",
        "",
        f"Generated: {generated}",
        "",
        "## Run Totals",
        "",
        f"- Current run jobs: {len(run_jobs)}",
        f"- Saved jobs in local outputs: {len(saved_jobs)}",
        f"- Email-eligible jobs: {len(newsletter.included_jobs)}",
        f"- Source warnings: {len(warnings)}",
        "",
        "## Target Position Checks",
        "",
    ]
    if not target_checks:
        lines.append("No target positions configured.")
    for check in target_checks:
        status = "FOUND" if check.found else "MISSING"
        lines.append(f"- {status}: {check.name}")
        lines.append(f"  Target: {check.title} - {check.institution}")
        lines.append(f"  URL: {check.url}")
        if check.matched_job:
            job = check.matched_job
            lines.append(f"  Matched: {job.title} - {job.institution}")
            lines.append(f"  Source: {job.source_name}")
            lines.append(f"  Fit: {job.fit_category} ({job.fit_score}/100)")
            lines.append(f"  Link: {job.application_url}")
    lines.extend(
        [
            "",
            "## Email-Eligible Jobs",
            "",
        ]
    )
    if newsletter.included_jobs:
        for job in newsletter.included_jobs:
            lines.append(
                f"- {job.fit_category} ({job.fit_score}/100): "
                f"{job.title} - {job.institution}"
            )
            lines.append(f"  Link: {job.application_url}")
    else:
        lines.append("None.")
    lines.extend(["", "## Source Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("None.")
    lines.extend(["", "## Newsletter Body", "", newsletter.body.strip(), ""])
    return "\n".join(lines)
