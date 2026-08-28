from pathlib import Path

from faculty_job_scout.config import load_config
from faculty_job_scout.models import JobPosting
from faculty_job_scout.scoring_rules import classify_role_type, score_job


def test_role_type_classification_includes_uk_lecturer_logic() -> None:
    assert classify_role_type("Lecturer in AI for Infrastructure", region="uk") == (
        "lecturer_ap_equivalent"
    )
    assert classify_role_type("Postdoctoral Researcher in Energy", region="us") == "regular_postdoc"
    assert (
        classify_role_type(
            "Assistant/Associate/Full Professor, Transportation Engineering and Systems",
            region="us",
        )
        == "open_rank"
    )
    assert (
        classify_role_type("Faculty Positions in Intelligent Transportation", region="mainland_china")
        == "open_rank"
    )


def test_teaching_only_titles_override_open_rank_and_assistant_professor_terms() -> None:
    assert (
        classify_role_type(
            "Open Rank: Lecturer or Senior Lecturer in Industrial Engineering and Operations Research",
            description="Lecturer in Discipline or Senior Lecturer in Discipline",
            region="us",
        )
        == "teaching_only"
    )
    assert classify_role_type("Stipendiary Lecturer in Engineering", region="uk") == "teaching_only"
    assert (
        classify_role_type("Visiting Assistant ProfessorVisiting Assistant Professor", region="us")
        == "teaching_only"
    )


def test_keyword_scoring_strong_fit() -> None:
    config = load_config(Path("config"))
    job = JobPosting(
        title="Tenure-Track Assistant Professor in Computational Science",
        institution="Example University",
        department="Department of Computational Science",
        source_name="test",
        source_url="https://example.edu/job",
        description_text=(
            "Optimization, machine learning, data science, statistical modeling, "
            "simulation, and computational methods."
        ),
        region="us",
    )

    result = score_job(job, config.keywords, config.institutions, config.settings)

    assert result.fit_category in {"A", "B"}
    assert result.fit_score >= 55
    assert result.role_type == "tenure_track_assistant_professor"


def test_negative_keywords_lower_score() -> None:
    config = load_config(Path("config"))
    keywords = dict(config.keywords)
    keywords["negative"] = ["clinical", "biomedical", "nursing"]
    job = JobPosting(
        title="Assistant Professor of Clinical Biomedical Materials",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/job",
        description_text="clinical medicine, biomedical materials, nursing",
        region="us",
    )

    result = score_job(job, keywords, config.institutions, config.settings)

    assert result.fit_category in {"C", "D"}
    assert result.warnings


def test_configured_negative_terms_are_low_relevance() -> None:
    config = load_config(Path("config"))
    keywords = dict(config.keywords)
    keywords["negative"] = ["omics", "immuno-engineering", "biomedical"]
    job = JobPosting(
        title="Omics Data Science for Immuno-Engineering",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/job",
        description_text="Omics data science for immuno-engineering and biomedical applications.",
        region="us",
    )

    result = score_job(job, keywords, config.institutions, config.settings)

    assert result.fit_category == "D"
    assert any("Negative keywords" in warning for warning in result.warnings)


def test_business_school_is_neutral_and_part_time_is_capped() -> None:
    config = load_config(Path("config"))
    business = JobPosting(
        title="Assistant Professor in Operations and Supply Chain",
        institution="Example University",
        school="School of Management",
        source_name="test",
        source_url="https://example.edu/business",
        description_text="Operations research, optimization, logistics, and data science.",
        region="uk",
    )
    part_time = JobPosting(
        title="Assistant Professor in Computational Systems",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/part-time",
        description_text="Part-time role in optimization, simulation, and machine learning.",
        region="us",
    )

    business_score = score_job(business, config.keywords, config.institutions, config.settings)
    part_time_score = score_job(part_time, config.keywords, config.institutions, config.settings)

    assert business_score.role_type == "assistant_professor"
    assert part_time_score.fit_score <= 54
    assert any("Part-time" in warning for warning in part_time_score.warnings)
