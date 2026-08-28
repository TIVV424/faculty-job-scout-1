from faculty_job_scout.job_preparation import prepare_jobs
from faculty_job_scout.models import JobPosting


def test_preparation_extracts_institution_and_school_from_description() -> None:
    job = JobPosting(
        title="Assistant Professor in Computational Science",
        institution="Institution not provided",
        source_name="test",
        source_url="https://board.example/job/1",
        description_text=(
            "The School of Engineering at University of Southern California invites "
            "applications in computational science."
        ),
    )

    prepared = prepare_jobs([job])

    assert prepared[0].institution == "University of Southern California"
    assert prepared[0].school == "School of Engineering"


def test_preparation_extracts_labeled_department() -> None:
    job = JobPosting(
        title=(
            "Assistant Professor in Metascience Personal type: Scientific staff "
            "Organisation: Department of Industrial Engineering & Innovation Sciences "
            "Apply no later than: 14-08-2026"
        ),
        institution="Eindhoven University of Technology",
        source_name="test",
        source_url="https://example.edu/job/1",
    )

    assert prepare_jobs([job])[0].department == (
        "Department of Industrial Engineering & Innovation Sciences"
    )


def test_preparation_merges_cross_source_duplicates_and_keeps_richer_fields() -> None:
    verbose = JobPosting(
        title=(
            "Assistant Professor in Metascience Personal type: Scientific staff "
            "Organisation: Department of Industrial Engineering"
        ),
        institution="Eindhoven University of Technology",
        source_name="official",
        source_url="https://jobs.tue.nl/metascience",
        description_text="Short card.",
    )
    rich = JobPosting(
        title="Assistant Professor in Metascience",
        institution="Eindhoven University of Technology",
        department="Department of Industrial Engineering",
        location="Eindhoven, Netherlands",
        source_name="Academic Positions",
        source_url="https://academicpositions.com/ad/metascience",
        description_text="A longer description of the research and teaching expectations.",
    )

    prepared = prepare_jobs([verbose, rich])

    assert len(prepared) == 1
    assert prepared[0].title == "Assistant Professor in Metascience"
    assert prepared[0].department == "Department of Industrial Engineering"
    assert prepared[0].location == "Eindhoven, Netherlands"
    assert prepared[0].description_text.startswith("A longer description")
