from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from faculty_job_scout.dedupe import build_canonical_id


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


@dataclass
class JobPosting:
    title: str
    institution: str
    source_name: str
    source_url: str
    canonical_id: str = ""
    id: int | None = None
    department: str = ""
    school: str = ""
    location: str = ""
    country: str = ""
    region: str = ""
    role_type: str = "other"
    application_url: str = ""
    description_text: str = ""
    deadline: str | None = None
    date_posted: str | None = None
    date_first_seen: str = field(default_factory=today_iso)
    date_last_seen: str = field(default_factory=today_iso)
    fit_category: str = "D"
    fit_score: int = 0
    summary: str = ""
    match_reasons: list[str] = field(default_factory=list)
    application_angle: str = ""
    required_materials: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_priority_institution: bool = False
    is_new_this_run: bool = True
    has_been_emailed: bool = False
    status: str = "active"
    notion_page_id: str = ""
    raw_html_path: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.application_url:
            self.application_url = self.source_url
        if not self.canonical_id:
            self.canonical_id = build_canonical_id(
                title=self.title,
                institution=self.institution,
                application_url=self.application_url,
            )

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [
                self.title,
                self.institution,
                self.department,
                self.school,
                self.location,
                self.country,
                self.region,
                self.description_text,
            ]
        )

    def to_db_record(self) -> dict[str, Any]:
        values = self.__dict__.copy()
        values["match_reasons"] = "\n".join(self.match_reasons)
        values["required_materials"] = "\n".join(self.required_materials)
        values["warnings"] = "\n".join(self.warnings)
        values["is_priority_institution"] = int(self.is_priority_institution)
        values["is_new_this_run"] = int(self.is_new_this_run)
        values["has_been_emailed"] = int(self.has_been_emailed)
        return values

    @classmethod
    def from_db_record(cls, record: dict[str, Any]) -> "JobPosting":
        values = dict(record)
        values["match_reasons"] = _split_lines(values.get("match_reasons"))
        values["required_materials"] = _split_lines(values.get("required_materials"))
        values["warnings"] = _split_lines(values.get("warnings"))
        values["is_priority_institution"] = bool(values.get("is_priority_institution"))
        values["is_new_this_run"] = bool(values.get("is_new_this_run"))
        values["has_been_emailed"] = bool(values.get("has_been_emailed"))
        return cls(**values)


def _split_lines(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [line for line in str(value).splitlines() if line.strip()]
