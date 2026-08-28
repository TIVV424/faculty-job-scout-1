from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from faculty_job_scout.models import JobPosting


class NotionClient(Protocol):
    def upsert(self, job: JobPosting, payload: dict) -> str:
        ...


@dataclass
class MockNotionClient:
    synced_payloads: list[dict]

    def upsert(self, job: JobPosting, payload: dict) -> str:
        self.synced_payloads.append(payload)
        return f"mock-notion-{job.canonical_id}"


def build_notion_payload(job: JobPosting, database_id: str) -> dict:
    properties = {
        "Title": {"title": [{"text": {"content": job.title}}]},
        "Institution": {"rich_text": [{"text": {"content": job.institution}}]},
        "Department": {"rich_text": [{"text": {"content": job.department}}]},
        "Country": {"select": {"name": job.country or "Unknown"}},
        "Region": {"select": {"name": job.region or "Unknown"}},
        "Role Type": {"select": {"name": job.role_type}},
        "Fit Category": {"select": {"name": job.fit_category}},
        "Fit Score": {"number": job.fit_score},
        "URL": {"url": job.application_url},
        "Source": {"rich_text": [{"text": {"content": job.source_name}}]},
        "Date First Seen": {"date": {"start": job.date_first_seen}},
        "Date Last Seen": {"date": {"start": job.date_last_seen}},
        "Status": {"select": {"name": job.status}},
        "Application Angle": {"rich_text": [{"text": {"content": job.application_angle}}]},
        "Summary": {"rich_text": [{"text": {"content": job.summary}}]},
        "Required Materials": {
            "multi_select": [{"name": material} for material in job.required_materials]
        },
        "Warnings": {"rich_text": [{"text": {"content": "; ".join(job.warnings)}}]},
    }
    if job.deadline:
        properties["Deadline"] = {"date": {"start": job.deadline}}
    return {"parent": {"database_id": database_id}, "properties": properties}


def sync_jobs_to_notion(
    jobs: list[JobPosting],
    database_id: str,
    client: NotionClient | None = None,
) -> list[JobPosting]:
    client = client or MockNotionClient([])
    for job in jobs:
        job.notion_page_id = client.upsert(job, build_notion_payload(job, database_id))
    return jobs
