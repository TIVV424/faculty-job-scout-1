from pathlib import Path

from faculty_job_scout.sources.rss import RssAdapter, parse_feed


FIXTURE = Path(__file__).parent / "fixtures" / "higheredjobs_cee.xml"
FEED_CONFIG = {
    "name": "HigherEdJobs CEE",
    "url": "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=115",
    "department": "Civil and Environmental Engineering",
}


def test_parse_higheredjobs_rss_fixture() -> None:
    jobs = parse_feed(FIXTURE.read_bytes(), FEED_CONFIG)

    assert len(jobs) == 2
    assert jobs[0].title == "Assistant Professor of Transportation Engineering"
    assert jobs[0].institution == "Example State University"
    assert jobs[0].location == "Ann Arbor, MI"
    assert jobs[0].date_posted == "2026-06-18"
    assert jobs[0].country == "United States"
    assert jobs[0].region == "us"
    assert jobs[1].institution == "Example Technical University"
    assert jobs[1].location == "Guangzhou, China"
    assert jobs[1].region == "mainland_china"


def test_rss_adapter_uses_injected_fetcher() -> None:
    calls: list[tuple[str, int, str]] = []

    def fetcher(url: str, timeout: int, user_agent: str) -> bytes:
        calls.append((url, timeout, user_agent))
        return FIXTURE.read_bytes()

    result = RssAdapter(
        [FEED_CONFIG],
        timeout_seconds=12,
        user_agent="test-agent",
        fetcher=fetcher,
    ).collect()

    assert len(result.jobs) == 2
    assert result.warnings == []
    assert calls == [(FEED_CONFIG["url"], 12, "test-agent")]


def test_rss_adapter_reports_fetch_failure() -> None:
    def failing_fetcher(url: str, timeout: int, user_agent: str) -> bytes:
        raise TimeoutError("request timed out")

    result = RssAdapter([FEED_CONFIG], fetcher=failing_fetcher).collect()

    assert result.jobs == []
    assert result.warnings == ["RSS feed 'HigherEdJobs CEE' failed: request timed out"]


def test_rss_adapter_reports_bot_block_page() -> None:
    def blocked_fetcher(url: str, timeout: int, user_agent: str) -> bytes:
        return b"<html><body>Request unsuccessful. Incapsula incident ID: 42</body></html>"

    result = RssAdapter([FEED_CONFIG], fetcher=blocked_fetcher).collect()

    assert result.jobs == []
    assert "blocked the automated RSS request" in result.warnings[0]


def test_rss_adapter_delays_between_enabled_feeds() -> None:
    sleeps: list[float] = []
    feeds = [
        {**FEED_CONFIG, "name": "Feed one"},
        {**FEED_CONFIG, "name": "Disabled", "enabled": False},
        {**FEED_CONFIG, "name": "Feed two"},
    ]

    result = RssAdapter(
        feeds,
        delay_seconds=2.5,
        fetcher=lambda url, timeout, user_agent: FIXTURE.read_bytes(),
        sleeper=sleeps.append,
    ).collect()

    assert len(result.jobs) == 2
    assert sleeps == [2.5]
