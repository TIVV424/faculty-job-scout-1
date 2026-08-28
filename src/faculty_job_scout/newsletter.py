from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from faculty_job_scout.models import JobPosting
from faculty_job_scout.scoring_rules import is_lower_priority_job


@dataclass(frozen=True)
class Newsletter:
    subject: str
    body: str
    included_jobs: list[JobPosting]


def should_include_in_email(job: JobPosting, settings: dict) -> bool:
    newsletter = settings.get("newsletter", {})
    main_categories = set(newsletter.get("include_categories_main", ["A", "B"]))
    if is_lower_priority_job(job) and job.fit_category == "C":
        return not job.has_been_emailed
    if job.fit_category in main_categories:
        return not job.has_been_emailed
    if (
        job.fit_category == "C"
        and job.is_priority_institution
        and newsletter.get("include_category_c_if_priority_institution", True)
    ):
        return not job.has_been_emailed
    if job.fit_category == "D":
        return bool(newsletter.get("include_category_d", False)) and not job.has_been_emailed
    return False


def build_newsletter(jobs: list[JobPosting], settings: dict, template: str) -> Newsletter:
    max_jobs = int(settings.get("newsletter", {}).get("max_jobs_per_section", 20))
    included = [job for job in jobs if should_include_in_email(job, settings)]
    lower_priority = _limit([job for job in included if is_lower_priority_job(job)], max_jobs)
    regular = [job for job in included if not is_lower_priority_job(job)]
    strong = _limit([job for job in regular if job.fit_category == "A"], max_jobs)
    good = _limit([job for job in regular if job.fit_category == "B"], max_jobs)
    possible = _limit(
        [job for job in regular if job.fit_category == "C" and job.is_priority_institution],
        max_jobs,
    )
    fellowships = _limit(
        [job for job in included if "fellowship" in job.role_type],
        max_jobs,
    )
    deadline_14 = _deadline_within(included, settings, "reminder_window_days")
    deadline_7 = _deadline_within(included, settings, "urgent_window_days")
    warnings = [job for job in included if job.warnings]
    sync_summary = f"Prepared {len(jobs)} job records; {len(included)} are email-eligible."
    summary = (
        f"{len(included)} new email-eligible postings. "
        f"{len(strong)} strong fits and {len(good)} good fits."
    )
    body = template.format(
        summary=summary,
        strong_fit=_render_jobs(strong),
        good_fit=_render_jobs(good),
        possible_priority=_render_jobs(possible),
        lower_priority=_render_compact_jobs(lower_priority),
        fellowships=_render_jobs(fellowships),
        deadlines_14=_render_jobs(deadline_14),
        deadlines_7=_render_jobs(deadline_7),
        warnings=_render_warnings(warnings),
        sync_summary=sync_summary,
    )
    subject_template = settings.get("newsletter", {}).get(
        "subject_template",
        "Faculty Job Scout: {num_new} new postings, {num_strong} strong fits",
    )
    subject = subject_template.format(num_new=len(included), num_strong=len(strong))
    return Newsletter(subject=subject, body=body, included_jobs=included)


def _limit(jobs: list[JobPosting], max_jobs: int) -> list[JobPosting]:
    return sorted(jobs, key=lambda job: job.fit_score, reverse=True)[:max_jobs]


def _deadline_within(jobs: list[JobPosting], settings: dict, key: str) -> list[JobPosting]:
    days = int(settings.get("deadline_reminders", {}).get(key, 0))
    today = date.today()
    selected = []
    for job in jobs:
        if not job.deadline:
            continue
        try:
            deadline = date.fromisoformat(job.deadline)
        except ValueError:
            continue
        if 0 <= (deadline - today).days <= days:
            selected.append(job)
    return selected


def _render_jobs(jobs: list[JobPosting]) -> str:
    if not jobs:
        return "None this week."
    chunks = []
    for job in jobs:
        deadline = job.deadline or "not listed"
        reasons = "; ".join(job.match_reasons[:3]) or "No detailed reasons yet."
        warnings = "; ".join(job.warnings[:2]) or "None noted."
        chunks.append(
            "\n".join(
                [
                    f"- {job.title} - {job.institution}",
                    f"  Department/school: {_render_unit(job)}",
                    f"  Location: {job.location or 'not listed'} ({job.country or job.region or 'unknown'})",
                    f"  Role: {job.role_type}; fit {job.fit_category} ({job.fit_score}/100)",
                    f"  Deadline: {deadline}",
                    f"  Link: {job.application_url}",
                    f"  Summary: {job.summary or 'No summary yet.'}",
                    f"  Match: {reasons}",
                    f"  Application angle: {job.application_angle or 'To draft.'}",
                    f"  Warnings: {warnings}",
                    f"  Source: {job.source_url}",
                    f"  First seen: {job.date_first_seen}",
                ]
            )
        )
    return "\n\n".join(chunks)


def _render_compact_jobs(jobs: list[JobPosting]) -> str:
    if not jobs:
        return "None this week."
    return "\n\n".join(
        "\n".join(
            [
                f"- {job.title} - {job.institution}",
                f"  Department/school: {_render_unit(job)}",
                f"  Role: {job.role_type}; fit {job.fit_category} ({job.fit_score}/100)",
                f"  Link: {job.application_url}",
            ]
        )
        for job in jobs
    )


def _render_unit(job: JobPosting) -> str:
    return " / ".join(value for value in (job.department, job.school) if value) or "not listed"


def _render_warnings(jobs: list[JobPosting]) -> str:
    if not jobs:
        return "No warnings for included jobs."
    return "\n".join(
        f"- {job.title} - {job.institution}: {'; '.join(job.warnings)}" for job in jobs
    )
