from __future__ import annotations

import csv
from pathlib import Path

from faculty_job_scout.db import JOB_COLUMNS
from faculty_job_scout.models import JobPosting


def export_jobs_csv(jobs: list[JobPosting], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOB_COLUMNS)
        writer.writeheader()
        for job in jobs:
            record = job.to_db_record()
            writer.writerow({column: record.get(column, "") for column in JOB_COLUMNS})
    return path
