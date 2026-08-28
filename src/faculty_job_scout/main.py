from __future__ import annotations

import argparse
import logging
import os
import re
import smtplib
import sys
from pathlib import Path

from faculty_job_scout.config import ConfigBundle, get_nested, load_config, resolve_project_path
from faculty_job_scout.csv_export import export_jobs_csv
from faculty_job_scout.db import connect, list_jobs, upsert_jobs
from faculty_job_scout.email_sender import (
    TEST_EMAIL_SUBJECT,
    MissingEmailEnvironmentVariables,
    load_email_credentials,
    send_email,
)
from faculty_job_scout.llm_scorer import OpenAIResponsesClient, score_with_llm
from faculty_job_scout.job_preparation import consolidate_jobs, prepare_jobs
from faculty_job_scout.logging_utils import configure_logging
from faculty_job_scout.models import JobPosting
from faculty_job_scout.newsletter import build_newsletter
from faculty_job_scout.notion_sync import sync_jobs_to_notion
from faculty_job_scout.run_summary import write_markdown_summary
from faculty_job_scout.scoring_rules import is_lower_priority_job, score_job
from faculty_job_scout.sources.base import SourceAdapter
from faculty_job_scout.sources.job_boards import JobBoardsAdapter
from faculty_job_scout.sources.rss import RssAdapter
from faculty_job_scout.sources.static_pages import StaticPagesAdapter

LOGGER = logging.getLogger(__name__)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect and score faculty job postings.")
    parser.add_argument("--config-dir", default="config", help="Path to YAML config directory.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Run without external side effects.")
    mode.add_argument("--once", action="store_true", help="Run one full collection cycle.")
    mode.add_argument(
        "--test-email",
        action="store_true",
        help="Send one Gmail SMTP configuration test email.",
    )
    mode.add_argument(
        "--test-llm",
        action="store_true",
        help="Score one built-in job without collecting, saving, or emailing.",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip email delivery and email credential validation.",
    )
    parser.add_argument(
        "--live-sources",
        action="store_true",
        help="Fetch configured live sources; combine with --dry-run to suppress delivery.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    if not args.dry_run and not args.once and not args.test_email and not args.test_llm:
        parser.error("Choose --dry-run, --once, --test-email, or --test-llm")
    if args.test_email and args.no_email:
        parser.error("--test-email cannot be combined with --no-email")
    config = load_config(args.config_dir)
    if args.test_llm:
        try:
            print(run_llm_smoke_test(config))
        except Exception as exc:
            print(f"ERROR: LLM smoke test failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.test_email:
        try:
            detail = send_test_email(config)
        except MissingEmailEnvironmentVariables as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except (OSError, smtplib.SMTPException) as exc:
            print(f"ERROR: Gmail SMTP test failed: {exc}", file=sys.stderr)
            return 1
        print(detail)
        return 0
    run_pipeline(
        config,
        dry_run=args.dry_run,
        live_sources=args.live_sources or args.once,
        no_email=args.no_email,
    )
    return 0


def run_pipeline(
    config: ConfigBundle,
    dry_run: bool = False,
    live_sources: bool = False,
    no_email: bool = False,
) -> dict[str, object]:
    warnings: list[str] = []
    jobs = collect_jobs(
        config,
        dry_run=dry_run,
        live_sources=live_sources,
        warnings=warnings,
    )
    scored_jobs = score_jobs(prepare_jobs(jobs), config, dry_run=dry_run)
    saved_jobs = persist_outputs(scored_jobs, config)
    notion_count = maybe_sync_notion(saved_jobs, config, dry_run=dry_run)
    newsletter = build_newsletter(saved_jobs, config.settings, config.email_template)
    summary_path = maybe_write_markdown_summary(
        run_jobs=scored_jobs,
        saved_jobs=saved_jobs,
        warnings=warnings,
        newsletter=newsletter,
        config=config,
    )
    email_detail = maybe_send_email(
        newsletter.subject,
        newsletter.body,
        config,
        dry_run=dry_run,
        no_email=no_email,
    )
    LOGGER.info(
        "Run complete: %s jobs, %s notion updates, email=%s, warnings=%s",
        len(saved_jobs),
        notion_count,
        email_detail,
        len(warnings),
    )
    for warning in warnings:
        LOGGER.warning(warning)
    return {
        "jobs": saved_jobs,
        "warnings": warnings,
        "notion_count": notion_count,
        "email": email_detail,
        "newsletter_subject": newsletter.subject,
        "summary_path": str(summary_path) if summary_path else "",
    }


def collect_jobs(
    config: ConfigBundle,
    dry_run: bool,
    warnings: list[str],
    live_sources: bool = False,
) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for adapter in build_source_adapters(config, dry_run=dry_run, live_sources=live_sources):
        try:
            result = adapter.collect()
        except Exception as exc:  # pragma: no cover - defensive source isolation
            warnings.append(f"Source {adapter.name} failed: {exc}")
            continue
        jobs.extend(result.jobs)
        warnings.extend(result.warnings)
        LOGGER.info("Collected %s jobs from %s", len(result.jobs), result.source_name)
    return jobs


def build_source_adapters(
    config: ConfigBundle,
    dry_run: bool,
    live_sources: bool = False,
) -> list[SourceAdapter]:
    source_config = config.sources.get("sources", {})
    adapters: list[SourceAdapter] = []
    job_boards = source_config.get("job_boards", {})
    if job_boards.get("enabled", False) and live_sources:
        scraping = config.settings.get("scraping", {})
        adapters.append(
            JobBoardsAdapter(
                job_boards.get("sources", []),
                timeout_seconds=int(scraping.get("request_timeout_seconds", 30)),
                delay_seconds=float(scraping.get("delay_between_requests_seconds", 2)),
                user_agent=str(scraping.get("user_agent", "faculty-job-scout/0.1")),
                respect_robots_txt=bool(scraping.get("respect_robots_txt", True)),
                max_detail_pages_per_source=int(
                    scraping.get("max_detail_pages_per_source", 25)
                ),
            )
        )
    official = source_config.get("official_pages", {})
    if official.get("enabled", False) and not live_sources:
        adapters.append(StaticPagesAdapter(official.get("pages", []), mock=True))
    elif official.get("enabled", False) and official.get("pages"):
        adapters.append(StaticPagesAdapter(official.get("pages", []), mock=False))
    rss = source_config.get("rss", {})
    if rss.get("enabled", False) and live_sources:
        adapters.append(
            RssAdapter(
                rss.get("feeds", []),
                timeout_seconds=int(
                    get_nested(
                        config.settings,
                        "scraping",
                        "request_timeout_seconds",
                        default=30,
                    )
                ),
                delay_seconds=float(
                    get_nested(
                        config.settings,
                        "scraping",
                        "delay_between_requests_seconds",
                        default=2,
                    )
                ),
                user_agent=str(
                    rss.get("user_agent")
                    or get_nested(
                        config.settings,
                        "scraping",
                        "user_agent",
                        default="faculty-job-scout/0.1",
                    )
                ),
            )
        )
    return adapters


def score_jobs(jobs: list[JobPosting], config: ConfigBundle, dry_run: bool) -> list[JobPosting]:
    scored = []
    min_rule = float(get_nested(config.settings, "openai", "min_rule_score_for_llm", default=0.35))
    openai_enabled = bool(get_nested(config.settings, "openai", "enabled", default=False))
    llm_client = None
    if openai_enabled and not dry_run:
        try:
            llm_client = OpenAIResponsesClient(
                model=str(get_nested(config.settings, "openai", "model", default="gpt-5.6-luna")),
                api_key_env_var=str(
                    get_nested(
                        config.settings,
                        "openai",
                        "api_key_env_var",
                        default="OPENAI_API_KEY",
                    )
                ),
            )
        except (ImportError, RuntimeError) as exc:
            LOGGER.warning("LLM scoring unavailable; using rule scores: %s", exc)
    for job in jobs:
        rule = score_job(job, config.keywords, config.institutions, config.settings)
        job.fit_category = rule.fit_category
        job.fit_score = rule.fit_score
        job.role_type = rule.role_type
        job.match_reasons = rule.reasons
        job.warnings = rule.warnings
        job.is_priority_institution = any("priority watchlist" in reason for reason in rule.reasons)
        job.summary = job.summary or _default_summary(job)
        job.application_angle = _default_angle(job)
        if llm_client and rule.rule_score >= min_rule:
            rule_warnings = list(job.warnings)
            try:
                job = score_with_llm(job, config.profile, llm_client)
                job.warnings = list(dict.fromkeys([*rule_warnings, *job.warnings]))
            except Exception as exc:
                LOGGER.warning("LLM scoring failed for %s; using rule score: %s", job.title, exc)
        elif dry_run:
            LOGGER.info("Skipping LLM for %s during dry run.", job.title)
        if is_lower_priority_job(job) and job.fit_score > 54:
            job.fit_score = 54
            job.fit_category = "C"
        scored.append(job)
    return scored


def persist_outputs(jobs: list[JobPosting], config: ConfigBundle) -> list[JobPosting]:
    settings = config.settings
    saved_jobs = jobs
    if get_nested(settings, "outputs", "sqlite", "enabled", default=True):
        db_path = resolve_project_path(
            config.root,
            get_nested(settings, "outputs", "sqlite", "path", default="data/faculty_jobs.sqlite"),
        )
        with connect(db_path) as connection:
            dedupe = settings.get("deduplication", {})
            upsert_jobs(
                connection,
                jobs,
                float(dedupe.get("fuzzy_title_threshold", 0.90)),
                float(dedupe.get("fuzzy_institution_threshold", 0.90)),
            )
            saved_jobs = consolidate_jobs(list_jobs(connection))
    if get_nested(settings, "outputs", "csv", "enabled", default=True):
        csv_path = resolve_project_path(
            config.root,
            get_nested(settings, "outputs", "csv", "path", default="data/faculty_jobs.csv"),
        )
        export_jobs_csv(saved_jobs, csv_path)
    return saved_jobs


def maybe_write_markdown_summary(
    *,
    run_jobs: list[JobPosting],
    saved_jobs: list[JobPosting],
    warnings: list[str],
    newsletter,
    config: ConfigBundle,
) -> Path | None:
    summary_config = get_nested(config.settings, "outputs", "markdown_summary", default={})
    if not summary_config.get("enabled", True):
        return None
    path = resolve_project_path(
        config.root,
        summary_config.get("path", "data/latest_run_summary.md"),
    )
    target_config = config.sources.get("sources", {}).get("target_positions", {})
    target_positions = target_config.get("positions", []) if target_config.get("enabled", True) else []
    return write_markdown_summary(
        run_jobs=run_jobs,
        saved_jobs=saved_jobs,
        warnings=warnings,
        newsletter=newsletter,
        target_positions=target_positions,
        path=path,
    )


def maybe_sync_notion(jobs: list[JobPosting], config: ConfigBundle, dry_run: bool) -> int:
    if dry_run or not get_nested(config.settings, "outputs", "notion", "enabled", default=False):
        return 0
    database_env = get_nested(
        config.settings,
        "outputs",
        "notion",
        "database_id_env_var",
        default="NOTION_DATABASE_ID",
    )
    database_id = os.getenv(database_env, "")
    if not database_id:
        LOGGER.warning("Notion enabled but %s is not set; skipping.", database_env)
        return 0
    sync_jobs_to_notion(jobs, database_id)
    return len(jobs)


def maybe_send_email(
    subject: str,
    body: str,
    config: ConfigBundle,
    dry_run: bool,
    no_email: bool = False,
) -> str:
    if no_email:
        return "Email disabled by --no-email."
    if not get_nested(config.settings, "email", "enabled", default=False):
        return "Email disabled."
    email_config = config.settings.get("email", {})
    try:
        credentials = load_email_credentials()
    except MissingEmailEnvironmentVariables as exc:
        LOGGER.error("%s", exc)
        return f"Email not sent. {exc}"
    result = send_email(
        sender=credentials.sender,
        recipient=credentials.recipient,
        password=credentials.password,
        subject=subject,
        body=body,
        smtp_host=email_config.get("smtp_host", "smtp.gmail.com"),
        smtp_port=int(email_config.get("smtp_port", 587)),
        use_tls=bool(email_config.get("use_tls", True)),
        dry_run=dry_run,
    )
    return result.detail


def send_test_email(config: ConfigBundle) -> str:
    credentials = load_email_credentials()
    email_config = config.settings.get("email", {})
    result = send_email(
        sender=credentials.sender,
        recipient=credentials.recipient,
        password=credentials.password,
        subject=TEST_EMAIL_SUBJECT,
        body=(
            "# Faculty Job Scout\n\n"
            "Gmail SMTP is configured correctly.\n\n"
            "## Formatting preview\n"
            "- Sample job card (test only) - Example University\n"
            "  Location: Example City\n"
            "  Role: assistant professor; fit A (90/100)\n"
            "  Link: https://example.com/jobs/sample\n"
            "  Summary: Headings, spacing, and clickable links are working."
        ),
        smtp_host=email_config.get("smtp_host", "smtp.gmail.com"),
        smtp_port=int(email_config.get("smtp_port", 587)),
        use_tls=bool(email_config.get("use_tls", True)),
    )
    return result.detail


def run_llm_smoke_test(config: ConfigBundle) -> str:
    job = JobPosting(
        title="Tenure-Track Assistant Professor in Computational Science",
        institution="Example Technical University",
        department="Department of Computational Science",
        source_name="LLM smoke test",
        source_url="https://example.edu/jobs/computational-science",
        description_text=(
            "The department seeks a tenure-track assistant professor researching optimization, "
            "machine learning, simulation, and data-driven methods. Responsibilities include "
            "research, graduate teaching, and supervision. "
            "Applications require a CV, research statement, and teaching statement."
        ),
        region="us",
    )
    rule = score_job(job, config.keywords, config.institutions, config.settings)
    job.fit_category = rule.fit_category
    job.fit_score = rule.fit_score
    job.role_type = rule.role_type
    job.match_reasons = rule.reasons
    job.warnings = rule.warnings
    client = OpenAIResponsesClient(
        model=str(get_nested(config.settings, "openai", "model", default="gpt-5.6-luna")),
        api_key_env_var=str(
            get_nested(
                config.settings,
                "openai",
                "api_key_env_var",
                default="OPENAI_API_KEY",
            )
        ),
    )
    scored = score_with_llm(job, config.profile, client)
    usage = client.last_usage
    return "\n".join(
        [
            f"Model: {client.model}",
            f"Fit: {scored.fit_category} ({scored.fit_score}/100)",
            f"Role: {scored.role_type}",
            f"Summary: {scored.summary}",
            f"Evidence: {'; '.join(scored.match_reasons)}",
            f"Application angle: {scored.application_angle}",
            f"Warnings: {'; '.join(scored.warnings) or 'none'}",
            "Tokens: "
            f"{usage.get('input_tokens', 0)} input, "
            f"{usage.get('output_tokens', 0)} output, "
            f"{usage.get('total_tokens', 0)} total",
        ]
    )


def _default_summary(job: JobPosting) -> str:
    return f"{job.title} at {job.institution}, sourced from {job.source_name}."


def _default_angle(job: JobPosting) -> str:
    unit = job.department or job.school or job.institution
    focus = _title_focus(job.title)
    return (
        f"Connect your strongest relevant research evidence to the advertised focus on {focus}, "
        f"and name one credible collaboration or teaching contribution in {unit}."
    )


def _title_focus(title: str) -> str:
    focus = title
    for marker in ("Personal type:", "Field of expertise:", "Organisation:", "Apply no later"):
        focus = focus.split(marker, 1)[0]
    focus = re.sub(
        r"^(?:open rank:?\s*)?(?:tenure[- ]track\s+)?(?:assistant|associate|full|research)\s+"
        r"professor(?:s)?(?:\s+(?:of|in))?\s*",
        "",
        focus,
        flags=re.IGNORECASE,
    ).strip(" -,:;")
    return focus or "the advertised research area"


if __name__ == "__main__":
    raise SystemExit(cli())
