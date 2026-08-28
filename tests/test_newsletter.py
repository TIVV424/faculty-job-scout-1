from pathlib import Path

from faculty_job_scout.config import load_config
from faculty_job_scout.models import JobPosting
from faculty_job_scout.newsletter import build_newsletter, should_include_in_email


def test_newsletter_filters_categories() -> None:
    config = load_config(Path("config"))
    a_job = JobPosting(
        title="Assistant Professor in Energy",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/a",
        fit_category="A",
        fit_score=90,
    )
    c_priority = JobPosting(
        title="Data Science Lecturer",
        institution="Example European University",
        source_name="test",
        source_url="https://example.edu/c",
        fit_category="C",
        fit_score=45,
        is_priority_institution=True,
    )
    d_job = JobPosting(
        title="Teaching-only Role",
        institution="Other",
        source_name="test",
        source_url="https://example.edu/d",
        fit_category="D",
        fit_score=10,
    )

    assert should_include_in_email(a_job, config.settings)
    assert should_include_in_email(c_priority, config.settings)
    assert not should_include_in_email(d_job, config.settings)


def test_build_newsletter_body() -> None:
    config = load_config(Path("config"))
    job = JobPosting(
        title="Assistant Professor in Computational Science",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/a",
        application_url="https://example.edu/apply",
        fit_category="A",
        fit_score=91,
        role_type="assistant_professor",
        summary="A good match.",
    )

    newsletter = build_newsletter([job], config.settings, config.email_template)

    assert "Faculty Job Scout:" in newsletter.subject
    assert "Assistant Professor in Computational Science" in newsletter.body
    assert newsletter.included_jobs == [job]


def test_lower_priority_roles_use_compact_section() -> None:
    config = load_config(Path("config"))
    job = JobPosting(
        title="Part-Time Assistant Professor in Operations",
        institution="Example University",
        school="School of Business",
        source_name="test",
        source_url="https://example.edu/a",
        application_url="https://example.edu/apply",
        fit_category="C",
        fit_score=50,
        role_type="assistant_professor",
        summary="This long summary should not appear in the compact card.",
    )

    newsletter = build_newsletter([job], config.settings, config.email_template)

    lower_section = newsletter.body.split(
        "## Lower-priority matches", 1
    )[1].split("## Prestigious fellowships", 1)[0]
    assert "Part-Time Assistant Professor in Operations" in lower_section
    assert "School of Business" in lower_section
    assert "This long summary" not in lower_section
