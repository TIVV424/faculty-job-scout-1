import pytest

import faculty_job_scout.email_sender as email_sender


def test_credentials_are_loaded_from_the_fixed_environment_variables() -> None:
    credentials = email_sender.load_email_credentials(
        {
            "GMAIL_SENDER_EMAIL": " sender@gmail.com ",
            "GMAIL_APP_PASSWORD": "app-password",
            "NEWSLETTER_RECIPIENT_EMAIL": " reader@example.com ",
            "UNRELATED_EMAIL_VARIABLE": "ignored@example.com",
        }
    )

    assert credentials.sender == "sender@gmail.com"
    assert credentials.password == "app-password"
    assert credentials.recipient == "reader@example.com"


def test_missing_credentials_error_lists_names_not_values() -> None:
    with pytest.raises(email_sender.MissingEmailEnvironmentVariables) as error:
        email_sender.load_email_credentials(
            {
                "GMAIL_SENDER_EMAIL": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "",
                "NEWSLETTER_RECIPIENT_EMAIL": "",
            }
        )

    assert error.value.missing_names == (
        "GMAIL_APP_PASSWORD",
        "NEWSLETTER_RECIPIENT_EMAIL",
    )
    assert "sender@gmail.com" not in str(error.value)


def test_send_email_uses_starttls_login_and_send_message(monkeypatch) -> None:
    calls = {}

    class MockSMTP:
        def __init__(self, host, port, timeout):
            calls["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def starttls(self):
            calls["starttls"] = True

        def login(self, sender, password):
            calls["login"] = (sender, password)

        def send_message(self, message):
            calls["message"] = message

    monkeypatch.setattr(email_sender.smtplib, "SMTP", MockSMTP)

    result = email_sender.send_email(
        sender="sender@gmail.com",
        recipient="reader@example.com",
        password="app-password",
        subject="Subject",
        body="Body",
    )

    assert result.sent is True
    assert calls["connection"] == ("smtp.gmail.com", 587, 30)
    assert calls["starttls"] is True
    assert calls["login"] == ("sender@gmail.com", "app-password")
    assert calls["message"]["Subject"] == "Subject"
    assert calls["message"]["To"] == "reader@example.com"
    assert calls["message"].get_content_type() == "multipart/alternative"


def test_html_email_renders_headings_job_cards_and_safe_links() -> None:
    body = """# Faculty Job Scout Weekly Digest

## Strong-fit new postings
- Assistant Professor <Energy> - Example University
  Link: https://example.edu/jobs/123?area=energy&level=faculty
  Summary: Optimization & control research.
"""

    message = email_sender.build_email_message(
        "sender@gmail.com",
        "reader@example.com",
        "Digest",
        body,
    )
    html_part = message.get_body(preferencelist=("html",))

    assert html_part is not None
    html = html_part.get_content()
    assert "<h1" in html
    assert "<h2" in html
    assert "Open job posting" in html
    assert 'href="https://example.edu/jobs/123?area=energy&amp;level=faculty"' in html
    assert "Assistant Professor &lt;Energy&gt;" in html
    assert "Optimization &amp; control research." in html


def test_dry_run_never_opens_an_smtp_connection(monkeypatch) -> None:
    def unexpected_smtp(*args, **kwargs):
        raise AssertionError("SMTP must not be opened during a dry run")

    monkeypatch.setattr(email_sender.smtplib, "SMTP", unexpected_smtp)

    result = email_sender.send_email(
        sender="sender@gmail.com",
        recipient="reader@example.com",
        password="app-password",
        subject="Subject",
        body="Body",
        dry_run=True,
    )

    assert result.sent is False
    assert result.detail == "Dry run: email was not sent."
