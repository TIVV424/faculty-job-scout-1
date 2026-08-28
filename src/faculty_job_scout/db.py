from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable

from faculty_job_scout.dedupe import find_duplicate, normalize_text
from faculty_job_scout.job_preparation import is_missing_institution, merge_job_postings
from faculty_job_scout.models import JobPosting, today_iso, utc_now_iso

JOB_COLUMNS = [
    "canonical_id",
    "title",
    "institution",
    "department",
    "school",
    "location",
    "country",
    "region",
    "role_type",
    "source_name",
    "source_url",
    "application_url",
    "description_text",
    "deadline",
    "date_posted",
    "date_first_seen",
    "date_last_seen",
    "fit_category",
    "fit_score",
    "summary",
    "match_reasons",
    "application_angle",
    "required_materials",
    "warnings",
    "is_priority_institution",
    "is_new_this_run",
    "has_been_emailed",
    "status",
    "notion_page_id",
    "raw_html_path",
    "created_at",
    "updated_at",
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            institution TEXT NOT NULL,
            department TEXT,
            school TEXT,
            location TEXT,
            country TEXT,
            region TEXT,
            role_type TEXT,
            source_name TEXT,
            source_url TEXT,
            application_url TEXT,
            description_text TEXT,
            deadline TEXT,
            date_posted TEXT,
            date_first_seen TEXT,
            date_last_seen TEXT,
            fit_category TEXT,
            fit_score INTEGER,
            summary TEXT,
            match_reasons TEXT,
            application_angle TEXT,
            required_materials TEXT,
            warnings TEXT,
            is_priority_institution INTEGER,
            is_new_this_run INTEGER,
            has_been_emailed INTEGER,
            status TEXT,
            notion_page_id TEXT,
            raw_html_path TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    connection.commit()


def list_jobs(connection: sqlite3.Connection) -> list[JobPosting]:
    rows = connection.execute("SELECT * FROM jobs").fetchall()
    return [JobPosting.from_db_record(dict(row)) for row in rows]


def upsert_jobs(
    connection: sqlite3.Connection,
    jobs: Iterable[JobPosting],
    fuzzy_title_threshold: float = 0.90,
    fuzzy_institution_threshold: float = 0.90,
) -> list[JobPosting]:
    existing = list_jobs(connection)
    by_canonical_id = {job.canonical_id: job for job in existing}
    by_url = {
        normalize_text(job.application_url): job for job in existing if job.application_url
    }
    by_institution: dict[str, list[JobPosting]] = {}
    for existing_job in existing:
        key = _institution_key(existing_job.institution)
        if key:
            by_institution.setdefault(key, []).append(existing_job)
    saved: list[JobPosting] = []
    for job in jobs:
        url_key = normalize_text(job.application_url)
        saved_job = by_canonical_id.get(job.canonical_id) or by_url.get(url_key)
        key = _institution_key(job.institution)
        match = None
        if not saved_job and key:
            match = find_duplicate(
                job,
                by_institution.get(key, []),
                fuzzy_title_threshold,
                fuzzy_institution_threshold,
            )
        if saved_job or match:
            if not saved_job:
                saved_job = by_canonical_id[match.canonical_id]
            merge_job_postings(saved_job, job)
            saved_job.is_new_this_run = False
            _update_job(connection, saved_job)
            job = saved_job
        else:
            _insert_job(connection, job)
            existing.append(job)
            by_canonical_id[job.canonical_id] = job
            if url_key:
                by_url[url_key] = job
            if key:
                by_institution.setdefault(key, []).append(job)
        saved.append(job)
    connection.commit()
    return saved


def _institution_key(value: str) -> str:
    if is_missing_institution(value):
        return ""
    return re.sub(r"^the\s+", "", normalize_text(value))


def _insert_job(connection: sqlite3.Connection, job: JobPosting) -> None:
    record = job.to_db_record()
    placeholders = ", ".join([f":{column}" for column in JOB_COLUMNS])
    connection.execute(
        f"INSERT INTO jobs ({', '.join(JOB_COLUMNS)}) VALUES ({placeholders})",
        {column: record.get(column) for column in JOB_COLUMNS},
    )


def _update_job(connection: sqlite3.Connection, job: JobPosting) -> None:
    record = job.to_db_record()
    record["date_last_seen"] = today_iso()
    record["updated_at"] = utc_now_iso()
    assignments = ", ".join(
        [
            f"{column} = :{column}"
            for column in JOB_COLUMNS
            if column not in {"canonical_id", "date_first_seen", "created_at", "has_been_emailed"}
        ]
    )
    connection.execute(
        f"UPDATE jobs SET {assignments} WHERE canonical_id = :canonical_id",
        {column: record.get(column) for column in JOB_COLUMNS},
    )
