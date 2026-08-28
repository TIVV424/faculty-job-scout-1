from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from faculty_job_scout.models import JobPosting
from faculty_job_scout.sources.base import SourceResult

Fetcher = Callable[[str, int, str], bytes]
Sleeper = Callable[[float], None]
MAX_FEED_BYTES = 5_000_000


class RssAdapter:
    name = "rss"

    def __init__(
        self,
        feeds: list[dict] | None = None,
        *,
        timeout_seconds: int = 30,
        delay_seconds: float = 0,
        user_agent: str = "faculty-job-scout/0.1",
        fetcher: Fetcher | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.feeds = feeds or []
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = max(0.0, delay_seconds)
        self.user_agent = user_agent
        self.fetcher = fetcher or fetch_feed
        self.sleeper = sleeper

    def collect(self) -> SourceResult:
        jobs: list[JobPosting] = []
        warnings: list[str] = []
        seen_urls: set[str] = set()

        attempted = 0
        for feed in self.feeds:
            if not feed.get("enabled", True):
                continue
            feed_name = str(feed.get("name") or "unnamed RSS feed")
            url = str(feed.get("url") or "").strip()
            if not url:
                warnings.append(f"RSS feed '{feed_name}' has no URL; skipping.")
                continue

            try:
                if attempted and self.delay_seconds:
                    self.sleeper(self.delay_seconds)
                attempted += 1
                timeout = int(feed.get("timeout_seconds", self.timeout_seconds))
                user_agent = str(feed.get("user_agent") or self.user_agent)
                payload = self.fetcher(url, timeout, user_agent)
                parsed_jobs = parse_feed(payload, feed)
            except Exception as exc:
                warnings.append(f"RSS feed '{feed_name}' failed: {exc}")
                continue

            for job in parsed_jobs:
                if job.application_url in seen_urls:
                    continue
                seen_urls.add(job.application_url)
                jobs.append(job)

        return SourceResult(self.name, jobs=jobs, warnings=warnings)


def fetch_feed(url: str, timeout_seconds: int, user_agent: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("feed URL must use http or https")

    request = Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "User-Agent": user_agent,
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("feed response exceeded 5 MB")
    return payload


def parse_feed(payload: bytes, feed: dict) -> list[JobPosting]:
    payload_preview = payload[:2_000].decode("utf-8", errors="ignore").lower()
    if any(
        marker in payload_preview
        for marker in ("incapsula", "request unsuccessful", "pardon our interruption")
    ):
        raise ValueError("HigherEdJobs blocked the automated RSS request")

    if payload.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        raise ValueError(
            "expected RSS/Atom XML but received HTML; the source may have blocked the request"
        )
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    if not entries:
        raise ValueError("response contained no RSS or Atom entries")
    jobs: list[JobPosting] = []

    for entry in entries:
        title = _child_text(entry, "title")
        link = _entry_link(entry)
        if not title or not link:
            continue

        raw_description = (
            _child_text(entry, "description")
            or _child_text(entry, "summary")
            or _child_text(entry, "content")
        )
        description = html_to_text(raw_description)
        description_institution, description_location = _split_higheredjobs_description(
            description
        )
        institution = (
            _extract_labeled_field(description, "Institution")
            or description_institution
            or str(feed.get("institution") or "Unknown institution")
        )
        location = (
            _extract_labeled_field(description, "Location")
            or description_location
            or str(feed.get("location") or "")
        )
        date_posted = _parse_date(
            _child_text(entry, "pubDate")
            or _child_text(entry, "published")
            or _child_text(entry, "updated")
        )

        configured_country = str(feed.get("country") or "")
        configured_region = str(feed.get("region") or "")
        inferred_country, inferred_region = _infer_location(location)
        jobs.append(
            JobPosting(
                title=html_to_text(title),
                institution=institution,
                department=str(feed.get("department") or ""),
                location=location,
                country=configured_country or inferred_country,
                region=configured_region or inferred_region,
                source_name=str(feed.get("name") or "RSS"),
                source_url=link,
                application_url=link,
                description_text=description,
                date_posted=date_posted,
            )
        )

    return jobs


def html_to_text(value: str) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in parser.text.splitlines()]
    return "\n".join(line for line in lines if line)


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def _entry_link(entry: ET.Element) -> str:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        if href:
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""


def _extract_labeled_field(text: str, label: str) -> str:
    labels = "Institution|Location|Category|Posted|Type|Salary"
    pattern = rf"(?:^|\n){re.escape(label)}\s*:\s*(.+?)(?=\n(?:{labels})\s*:|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _split_higheredjobs_description(description: str) -> tuple[str, str]:
    match = re.fullmatch(r"(.+)\s+\(([^()]*)\)", description.strip())
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip()


def _parse_date(value: str) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _infer_location(location: str) -> tuple[str, str]:
    normalized = re.sub(r"[^a-z]+", " ", location.lower()).strip()
    if not normalized:
        return "", ""

    us_states = {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
        "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
        "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
        "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee",
        "texas", "utah", "vermont", "virginia", "washington", "west virginia",
        "wisconsin", "wyoming", "district of columbia", "united states", "usa",
    }
    us_abbreviations = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga",
        "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma",
        "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny",
        "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx",
        "ut", "vt", "va", "wa", "wv", "wi", "wy",
    }
    location_parts = {part.lower() for part in re.findall(r"\b[A-Z]{2}\b", location)}
    if (
        any(re.search(rf"\b{re.escape(state)}\b", normalized) for state in us_states)
        or bool(location_parts & us_abbreviations)
    ):
        return "United States", "us"

    country_regions = {
        "canada": ("Canada", "canada"),
        "united kingdom": ("United Kingdom", "uk"),
        "england": ("United Kingdom", "uk"),
        "scotland": ("United Kingdom", "uk"),
        "wales": ("United Kingdom", "uk"),
        "sweden": ("Sweden", "nordics"),
        "denmark": ("Denmark", "nordics"),
        "finland": ("Finland", "nordics"),
        "norway": ("Norway", "nordics"),
        "switzerland": ("Switzerland", "switzerland"),
        "australia": ("Australia", "australia"),
        "hong kong": ("Hong Kong", "hong_kong"),
        "singapore": ("Singapore", "singapore"),
        "china": ("China", "mainland_china"),
    }
    for marker, metadata in country_regions.items():
        if re.search(rf"\b{re.escape(marker)}\b", normalized):
            return metadata
    return "", ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class _TextExtractor(HTMLParser):
    _BREAK_TAGS = {"br", "div", "li", "p", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._BREAK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BREAK_TAGS - {"br"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)
