from faculty_job_scout.models import JobPosting
from faculty_job_scout.newsletter import Newsletter
from faculty_job_scout.run_summary import check_target_positions, write_markdown_summary


def test_target_position_check_matches_current_run_jobs_by_title_and_institution() -> None:
    jobs = [
        JobPosting(
            title="Assistant Professor",
            institution="Eindhoven University of Technology",
            source_name="TU/e Vacancies",
            source_url="https://jobs.tue.nl/en/vacancies",
            application_url="https://jobs.tue.nl/en/working-at-tue/vacancy-overview?filters=1130&search=",
            description_text="Generic role filter.",
        ),
        JobPosting(
            title="Assistant Professor in Sustainable Agentic AI",
            institution="Eindhoven University of Technology",
            source_name="TU/e Vacancies",
            source_url="https://jobs.tue.nl/en/vacancies",
            application_url="https://jobs.tue.nl/en/vacancy/assistant-professor-in-sustainable-agentic-ai",
            description_text="Sustainable AI systems.",
        )
    ]
    targets = [
        {
            "name": "TU/e Sustainable Agentic AI",
            "url": "https://www.tue.nl/en/working-at-tue/vacancy-overview/assistant-professor-in-sustainable-agentic-ai",
            "title": "Assistant Professor in Sustainable Agentic AI",
            "institution": "Eindhoven University of Technology",
        }
    ]

    checks = check_target_positions(jobs, targets)

    assert checks[0].found is True
    assert checks[0].matched_job is jobs[1]


def test_target_position_check_reports_missing_when_not_collected() -> None:
    checks = check_target_positions(
        [],
        [
            {
                "name": "Example Applied Mathematics",
                "url": "https://example.edu/jobs/applied-mathematics",
                "title": "Assistant Professor in Mathematics with Specialization in Applied Mathematics",
                "institution": "Example University",
            }
        ],
    )

    assert checks[0].found is False
    assert checks[0].matched_job is None


def test_markdown_summary_writes_target_checks(tmp_path) -> None:
    job = JobPosting(
        title="Academic Position in Applied Mathematics",
        institution="Example University",
        source_name="Example Source",
        source_url="https://example.edu/jobs/applied-mathematics",
        application_url="https://example.edu/jobs/applied-mathematics",
        description_text="Applied mathematics.",
        fit_category="C",
        fit_score=42,
    )
    newsletter = Newsletter(subject="Subject", body="Newsletter body", included_jobs=[])
    path = tmp_path / "latest_run_summary.md"

    write_markdown_summary(
        run_jobs=[job],
        saved_jobs=[job],
        warnings=["sample warning"],
        newsletter=newsletter,
        target_positions=[
            {
                "name": "Example Applied Mathematics",
                "url": job.application_url,
                "title": job.title,
                "institution": job.institution,
            }
        ],
        path=path,
    )

    text = path.read_text(encoding="utf-8")
    assert "FOUND: Example Applied Mathematics" in text
    assert "sample warning" in text
    assert "Newsletter body" in text
