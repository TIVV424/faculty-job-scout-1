from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from faculty_job_scout.models import JobPosting


@dataclass(frozen=True)
class SourceResult:
    source_name: str
    jobs: list[JobPosting] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SourceAdapter(Protocol):
    name: str

    def collect(self) -> SourceResult:
        ...
