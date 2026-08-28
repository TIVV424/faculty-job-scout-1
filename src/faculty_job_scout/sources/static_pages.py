from __future__ import annotations

from faculty_job_scout.models import JobPosting
from faculty_job_scout.sources.base import SourceResult


class StaticPagesAdapter:
    name = "official_pages"

    def __init__(self, pages: list[dict] | None = None, mock: bool = True) -> None:
        self.pages = pages or []
        self.mock = mock

    def collect(self) -> SourceResult:
        if self.mock or not self.pages:
            return SourceResult(self.name, jobs=_mock_jobs())
        warnings = [
            "Official page scraping is configured but not implemented for live HTTP in v0; "
            "using zero live jobs."
        ]
        return SourceResult(self.name, jobs=[], warnings=warnings)


def _mock_jobs() -> list[JobPosting]:
    return [
        JobPosting(
            title="Tenure-Track Assistant Professor in Computational Science",
            institution="Example University",
            department="Department of Computational Science",
            school="College of Science",
            location="Example City",
            country="United States",
            region="us",
            source_name="Mock Official Careers",
            source_url="https://example.edu/jobs/computational-science",
            application_url="https://example.edu/apply/computational-science",
            description_text=(
                "Tenure-track assistant professor role in optimization, machine learning, "
                "statistical modeling, simulation, teaching, and interdisciplinary research."
            ),
        ),
        JobPosting(
            title="Lecturer in Data Science",
            institution="Example European University",
            department="Department of Data Science",
            location="Example City",
            country="United Kingdom",
            region="uk",
            source_name="Mock Official Careers",
            source_url="https://example.ac.uk/jobs/data-science",
            application_url="https://example.ac.uk/apply/data-science",
            description_text=(
                "Lecturer position focused on machine learning, reproducible science, "
                "collaborative research, and teaching."
            ),
        ),
        JobPosting(
            title="Postdoctoral Researcher in Experimental Chemistry",
            institution="Example Institute",
            department="Department of Chemistry",
            location="Example City",
            country="Canada",
            region="canada",
            source_name="Mock Official Careers",
            source_url="https://example.ca/jobs/chemistry",
            application_url="https://example.ca/apply/chemistry",
            description_text="Laboratory research role in experimental chemistry.",
        ),
    ]
