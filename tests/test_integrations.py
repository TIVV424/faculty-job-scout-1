from types import SimpleNamespace

import pytest

from faculty_job_scout.email_sender import build_email_message
from faculty_job_scout.llm_scorer import (
    ALLOWED_ROLE_TYPES,
    JobAssessment,
    OpenAIResponsesClient,
    validate_llm_response,
)
from faculty_job_scout.models import JobPosting
from faculty_job_scout.notion_sync import build_notion_payload


def test_notion_payload_construction() -> None:
    job = JobPosting(
        title="Assistant Professor in Energy",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/job",
        fit_category="A",
        fit_score=88,
        role_type="assistant_professor",
        required_materials=["CV", "research statement"],
    )

    payload = build_notion_payload(job, "database-id")

    assert payload["parent"]["database_id"] == "database-id"
    assert payload["properties"]["Title"]["title"][0]["text"]["content"] == job.title
    assert payload["properties"]["Required Materials"]["multi_select"][0]["name"] == "CV"


def test_llm_schema_validation() -> None:
    score = validate_llm_response(
        {
            "fit_category": "A",
            "fit_score": 92,
            "role_type": "assistant_professor",
            "summary": "Strong fit.",
            "match_reasons": ["energy"],
            "application_angle": "Lead with computational modeling.",
            "required_materials": ["CV"],
            "warnings": [],
            "deadline": None,
            "confidence": 0.9,
        }
    )

    assert score.fit_score == 92


@pytest.mark.parametrize(
    "role_type",
    ["tenure_track_assistant_professor", "regular_postdoc", "teaching_only"],
)
def test_llm_schema_accepts_rule_classifier_role_types(role_type: str) -> None:
    score = validate_llm_response(
        {
            "fit_category": "B",
            "fit_score": 60,
            "role_type": role_type,
            "confidence": 0.8,
        }
    )

    assert score.role_type == role_type


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("assistant professor", "assistant_professor"),
        ("Lecturer or Senior Lecturer", "lecturer_ap_equivalent"),
        ("Non-Tenure: Open Rank and Title", "open_rank"),
        ("unclear / malformed job-listing page", "other"),
    ],
)
def test_llm_schema_normalizes_observed_role_labels(label: str, expected: str) -> None:
    score = validate_llm_response(
        {
            "fit_category": "C",
            "fit_score": 45,
            "role_type": label,
            "confidence": 0.6,
        }
    )

    assert score.role_type == expected


def test_openai_structured_schema_constrains_role_type() -> None:
    schema = JobAssessment.model_json_schema()

    assert set(schema["$defs"]["RoleType"]["enum"]) == ALLOWED_ROLE_TYPES


def test_llm_schema_rejects_bad_category() -> None:
    with pytest.raises(ValueError):
        validate_llm_response(
            {
                "fit_category": "Z",
                "fit_score": 50,
                "role_type": "assistant_professor",
                "confidence": 0.5,
            }
        )


def test_openai_client_uses_structured_dimensions_and_python_score() -> None:
    assessment = JobAssessment(
        research_topic_fit=5,
        methods_fit=4,
        career_stage_fit=5,
        department_fit=4,
        teaching_fit=3,
        role_type="tenure_track_assistant_professor",
        summary="Strong computational-science fit.",
        evidence=["The call explicitly requests optimization for EV infrastructure."],
        application_angle="Connect computational methods to the department's research agenda.",
        required_materials=["CV", "research statement"],
        warnings=[],
        deadline="2026-10-01",
        confidence=0.9,
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["model"] == "gpt-5.6-luna"
            assert kwargs["text_format"] is JobAssessment
            return SimpleNamespace(
                output_parsed=assessment,
                usage=SimpleNamespace(input_tokens=300, output_tokens=100, total_tokens=400),
            )

    client = OpenAIResponsesClient(
        model="gpt-5.6-luna",
        sdk_client=SimpleNamespace(responses=FakeResponses()),
    )
    job = JobPosting(
        title="Assistant Professor in EV Infrastructure",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/job",
        description_text="Optimization and machine learning for complex systems.",
    )

    result = client.score(job, {"profile": {"interests": ["computational methods"]}})

    assert result["fit_score"] == 88
    assert result["fit_category"] == "A"
    assert result["match_reasons"] == assessment.evidence
    assert client.last_usage["total_tokens"] == 400


def test_email_body_generation() -> None:
    message = build_email_message(
        "sender@example.com",
        "recipient@example.com",
        "Subject",
        "Plain text body",
    )

    assert message["Subject"] == "Subject"
    plain_body = message.get_body(preferencelist=("plain",))
    html_body = message.get_body(preferencelist=("html",))
    assert plain_body is not None
    assert html_body is not None
    assert "Plain text body" in plain_body.get_content()
    assert "Plain text body" in html_body.get_content()
