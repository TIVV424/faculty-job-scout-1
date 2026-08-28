from faculty_job_scout.models import JobPosting


def test_job_roundtrip_db_record() -> None:
    job = JobPosting(
        title="Assistant Professor in Systems Engineering",
        institution="CMU",
        source_name="test",
        source_url="https://example.edu/job",
        match_reasons=["reason"],
        required_materials=["CV"],
        warnings=["warning"],
        is_priority_institution=True,
    )

    roundtrip = JobPosting.from_db_record(job.to_db_record())

    assert roundtrip.match_reasons == ["reason"]
    assert roundtrip.required_materials == ["CV"]
    assert roundtrip.warnings == ["warning"]
    assert roundtrip.is_priority_institution is True
