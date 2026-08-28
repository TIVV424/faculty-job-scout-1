from pathlib import Path

import faculty_job_scout.main as main_module
from faculty_job_scout.config import load_config
from faculty_job_scout.email_sender import EmailResult, TEST_EMAIL_SUBJECT
from faculty_job_scout.main import build_source_adapters, maybe_send_email, run_pipeline
from faculty_job_scout.sources.job_boards import JobBoardsAdapter
from faculty_job_scout.sources.rss import RssAdapter


def test_dry_run_pipeline(tmp_path) -> None:
    config = load_config(Path("config"))
    settings = dict(config.settings)
    settings["outputs"] = dict(config.settings["outputs"])
    settings["outputs"]["sqlite"] = {"enabled": True, "path": str(tmp_path / "jobs.sqlite")}
    settings["outputs"]["csv"] = {"enabled": True, "path": str(tmp_path / "jobs.csv")}
    settings["outputs"]["markdown_summary"] = {
        "enabled": True,
        "path": str(tmp_path / "latest_run_summary.md"),
    }
    config = config.__class__(
        root=tmp_path,
        settings=settings,
        profile=config.profile,
        keywords=config.keywords,
        institutions=config.institutions,
        sources=config.sources,
        email_template=config.email_template,
    )
    result = run_pipeline(config, dry_run=True, no_email=True)

    assert len(result["jobs"]) >= 1
    assert (tmp_path / "jobs.csv").exists()
    assert (tmp_path / "latest_run_summary.md").exists()
    assert result["email"] == "Email disabled by --no-email."


def test_cli_supports_dry_run_without_email(monkeypatch) -> None:
    invocation = {}

    def fake_run_pipeline(config, **kwargs):
        invocation.update(kwargs)
        return {}

    monkeypatch.setattr(main_module, "run_pipeline", fake_run_pipeline)

    assert main_module.cli(["--dry-run", "--no-email"]) == 0
    assert invocation == {"dry_run": True, "live_sources": False, "no_email": True}


def test_cli_runs_llm_smoke_test(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_module, "run_llm_smoke_test", lambda config: "Model: test")

    assert main_module.cli(["--test-llm"]) == 0
    assert "Model: test" in capsys.readouterr().out


def test_cli_sends_test_email_with_exact_subject(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GMAIL_SENDER_EMAIL", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.setenv("NEWSLETTER_RECIPIENT_EMAIL", "reader@example.com")
    sent = {}

    def fake_send_email(**kwargs):
        sent.update(kwargs)
        return EmailResult(sent=True, detail="Test message sent.")

    monkeypatch.setattr(main_module, "send_email", fake_send_email)

    assert main_module.cli(["--test-email"]) == 0
    assert sent["subject"] == TEST_EMAIL_SUBJECT
    assert sent["sender"] == "sender@gmail.com"
    assert sent["recipient"] == "reader@example.com"
    assert "Sample job card (test only)" in sent["body"]
    assert "Test message sent." in capsys.readouterr().out


def test_cli_test_email_lists_missing_environment_variable_names(monkeypatch, capsys) -> None:
    for name in (
        "GMAIL_SENDER_EMAIL",
        "GMAIL_APP_PASSWORD",
        "NEWSLETTER_RECIPIENT_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert main_module.cli(["--test-email"]) == 2
    error = capsys.readouterr().err
    assert "GMAIL_SENDER_EMAIL" in error
    assert "GMAIL_APP_PASSWORD" in error
    assert "NEWSLETTER_RECIPIENT_EMAIL" in error


def test_enabled_email_reports_missing_names_without_secret_values(monkeypatch, caplog) -> None:
    config = load_config(Path("config"))
    monkeypatch.setenv("GMAIL_SENDER_EMAIL", "private-sender@gmail.com")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("NEWSLETTER_RECIPIENT_EMAIL", raising=False)

    detail = maybe_send_email("Subject", "Body", config, dry_run=False)

    assert "GMAIL_APP_PASSWORD" in detail
    assert "NEWSLETTER_RECIPIENT_EMAIL" in detail
    assert "private-sender@gmail.com" not in detail
    assert "private-sender@gmail.com" not in caplog.text


def test_live_sources_build_enabled_adapters() -> None:
    config = load_config(Path("config"))

    adapters = build_source_adapters(config, dry_run=True, live_sources=True)

    assert any(isinstance(adapter, JobBoardsAdapter) for adapter in adapters)
    assert not any(isinstance(adapter, RssAdapter) for adapter in adapters)


def test_application_angle_is_tailored_after_llm_scoring(monkeypatch) -> None:
    config = load_config(Path("config"))
    job = main_module.JobPosting(
        title="Tenure-Track Assistant Professor in Computational Science",
        institution="Example University",
        department="Department of Computational Science",
        source_name="test",
        source_url="https://example.edu/job",
        description_text="Optimization, simulation, machine learning, and data science.",
        region="us",
        application_angle="Old custom angle.",
    )

    monkeypatch.setattr(main_module, "OpenAIResponsesClient", lambda **kwargs: object())

    def fake_score_with_llm(job, profile, client):
        job.application_angle = "LLM-generated angle."
        return job

    monkeypatch.setattr(main_module, "score_with_llm", fake_score_with_llm)

    scored = main_module.score_jobs([job], config, dry_run=False)

    assert scored[0].application_angle == "LLM-generated angle."


def test_llm_failure_keeps_rule_score(monkeypatch, caplog) -> None:
    config = load_config(Path("config"))
    job = main_module.JobPosting(
        title="Assistant Professor in Computational Modeling",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/job",
        description_text="Optimization, simulation, machine learning, and data science.",
        region="us",
    )
    monkeypatch.setattr(main_module, "OpenAIResponsesClient", lambda **kwargs: object())

    def failed_score(job, profile, client):
        raise RuntimeError("temporary API failure")

    monkeypatch.setattr(main_module, "score_with_llm", failed_score)

    scored = main_module.score_jobs([job], config, dry_run=False)

    assert scored[0].fit_score >= 35
    assert "using rule score" in caplog.text


def test_application_angles_use_advertised_focus() -> None:
    config = load_config(Path("config"))
    modeling = main_module.JobPosting(
        title="Assistant Professor in Computational Modeling",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/modeling",
        description_text="Optimization, simulation, and statistical modeling.",
        region="us",
    )
    data_science = main_module.JobPosting(
        title="Assistant Professor in Data Science",
        institution="Example University",
        source_name="test",
        source_url="https://example.edu/data-science",
        description_text="Machine learning and reproducible data science.",
        region="us",
    )

    scored = main_module.score_jobs([modeling, data_science], config, dry_run=True)

    assert "Computational Modeling" in scored[0].application_angle
    assert "Data Science" in scored[1].application_angle
    assert scored[0].application_angle != scored[1].application_angle
