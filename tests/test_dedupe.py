from faculty_job_scout.dedupe import build_canonical_id, find_duplicate, normalize_text
from faculty_job_scout.models import JobPosting


def test_normalize_text_removes_noise() -> None:
    assert normalize_text(" Example  University! ") == "example university"


def test_canonical_id_prefers_application_url() -> None:
    left = build_canonical_id("A", "B", "https://example.edu/apply")
    right = build_canonical_id("Different", "Different", "https://example.edu/apply")

    assert left == right


def test_find_duplicate_by_fuzzy_title_and_institution() -> None:
    existing = JobPosting(
        title="Assistant Professor in Computational Science",
        institution="Example University",
        source_name="x",
        source_url="https://example.edu/one",
        application_url="",
    )
    candidate = JobPosting(
        title="Assistant Professor, Computational Science",
        institution="Example University",
        source_name="x",
        source_url="https://example.edu/two",
        application_url="",
    )

    match = find_duplicate(candidate, [existing])

    assert match is not None
    assert match.reason in {"canonical_id", "fuzzy_title_institution"}
