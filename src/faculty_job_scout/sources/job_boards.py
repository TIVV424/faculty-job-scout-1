from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from faculty_job_scout.job_preparation import enrich_job_metadata, merge_job_postings
from faculty_job_scout.models import JobPosting
from faculty_job_scout.sources.base import SourceResult

Fetcher = Callable[[str, int, str], bytes]
RobotsChecker = Callable[[str, str], bool]
Sleeper = Callable[[float], None]

MAX_PAGE_BYTES = 8_000_000
ROLE_TERMS = re.compile(
    r"\b(?:assistant|associate|full|open[ -]?rank|tenure[ -]?track|visiting|teaching)?\s*"
    r"(?:professor|lecturer|faculty|(?:faculty|research|postdoctoral) fellow|"
    r"postdoc(?:toral)?|research scientist|"
    r"research associate|department chair|academic position)\b",
    re.IGNORECASE,
)
DETAIL_PATH = re.compile(
    r"/(?:job|jobs|position|positions|vacancy|vacancies|opportunity|opportunities|"
    r"opening|openings|post|posts|ad|advert|details?)(?:/|[-_.?])",
    re.IGNORECASE,
)
GENERIC_LINK_TEXT = {
    "job",
    "jobs",
    "search jobs",
    "view jobs",
    "view posting",
    "all jobs",
    "careers",
    "opportunities",
    "find jobs & opportunities",
    "search for jobs",
    "search for hosting",
    "academic jobs",
    "faculty jobs",
    "learn more",
    "read more",
    "details",
    "apply",
    "apply now",
    "post a job",
    "post a job vacancy",
    "hire faculty & staff",
    "job openings",
    "next",
    "previous",
}
DETAIL_FALLBACK_TEXT = {
    "apply",
    "apply now",
    "details",
    "read more",
    "learn more",
    "view posting",
}
BLOCK_MARKERS = (
    "access denied",
    "cloudflare ray id",
    "enable javascript and cookies to continue",
    "pardon our interruption",
    "request unsuccessful",
)


@dataclass(frozen=True)
class ParsedBoardPage:
    jobs: list[JobPosting]
    structured_jobs: int
    candidate_links: int


class JobBoardsAdapter:
    name = "job_boards"

    def __init__(
        self,
        sources: list[dict] | None = None,
        *,
        timeout_seconds: int = 30,
        delay_seconds: float = 2,
        user_agent: str = "faculty-job-scout/0.1",
        respect_robots_txt: bool = True,
        max_candidates_per_source: int = 150,
        max_detail_pages_per_source: int = 25,
        fetcher: Fetcher | None = None,
        robots_checker: RobotsChecker | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.sources = sources or []
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = max(0.0, delay_seconds)
        self.user_agent = user_agent
        self.respect_robots_txt = respect_robots_txt
        self.max_candidates_per_source = max_candidates_per_source
        self.max_detail_pages_per_source = max(0, max_detail_pages_per_source)
        self.fetcher = fetcher or fetch_html_page
        self.robots_checker = robots_checker or self._robots_allowed
        self.sleeper = sleeper
        self._robots_cache: dict[str, RobotFileParser | bool] = {}

    def collect(self) -> SourceResult:
        jobs: list[JobPosting] = []
        warnings: list[str] = []
        seen_urls: set[str] = set()
        attempted = 0

        for source in self.sources:
            if not source.get("enabled", True):
                continue
            source_name = str(source.get("name") or "unnamed job board")
            url = str(source.get("url") or "").strip()
            if not _is_http_url(url):
                warnings.append(f"Job board '{source_name}' has no valid HTTP(S) URL; skipped.")
                continue

            try:
                if self.respect_robots_txt and not self.robots_checker(url, self.user_agent):
                    warnings.append(f"Job board '{source_name}' disallows this page in robots.txt; skipped.")
                    continue
                if attempted and self.delay_seconds:
                    self.sleeper(self.delay_seconds)
                attempted += 1
                timeout = int(source.get("timeout_seconds", self.timeout_seconds))
                payload = self.fetcher(url, timeout, self.user_agent)
                parsed = parse_job_board_page(
                    payload,
                    source,
                    url,
                    max_candidates=int(
                        source.get("max_candidates", self.max_candidates_per_source)
                    ),
                )
            except Exception as exc:
                warnings.append(f"Job board '{source_name}' failed: {exc}")
                continue

            detail_limit = int(
                source.get("max_detail_pages", self.max_detail_pages_per_source)
            )
            detail_candidates = [job for job in parsed.jobs if _needs_detail_page(job)][
                :detail_limit
            ]
            detail_failures = 0
            for job in detail_candidates:
                try:
                    if self.respect_robots_txt and not self.robots_checker(
                        job.application_url, self.user_agent
                    ):
                        detail_failures += 1
                        continue
                    if self.delay_seconds:
                        self.sleeper(self.delay_seconds)
                    detail_payload = self.fetcher(
                        job.application_url,
                        int(source.get("timeout_seconds", self.timeout_seconds)),
                        self.user_agent,
                    )
                    enrich_job_from_detail_page(detail_payload, job, source)
                except Exception:
                    detail_failures += 1
            if detail_failures:
                warnings.append(
                    f"Job board '{source_name}' could not enrich {detail_failures} of "
                    f"{len(detail_candidates)} detail page(s)."
                )

            added = 0
            for job in parsed.jobs:
                if job.application_url in seen_urls:
                    continue
                seen_urls.add(job.application_url)
                jobs.append(job)
                added += 1

            if not parsed.jobs:
                warnings.append(
                    f"Job board '{source_name}' returned no extractable job links; "
                    "it may require JavaScript, authentication, or a more specific search URL."
                )
            elif parsed.candidate_links:
                warnings.append(
                    f"Job board '{source_name}' exposed {parsed.candidate_links} candidate "
                    f"link(s) without structured job data; {added} were new after deduplication."
                )

        return SourceResult(self.name, jobs=jobs, warnings=warnings)

    def _robots_allowed(self, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        cached = self._robots_cache.get(origin)
        if isinstance(cached, RobotFileParser):
            return cached.can_fetch(user_agent, url)
        if isinstance(cached, bool):
            return cached

        robots_url = urljoin(origin, "/robots.txt")
        parser = RobotFileParser(robots_url)
        try:
            request = Request(
                robots_url,
                headers={"User-Agent": user_agent, "Accept": "text/plain"},
            )
            with urlopen(request, timeout=min(self.timeout_seconds, 10)) as response:
                text = response.read(500_000).decode("utf-8", errors="replace")
            parser.parse(text.splitlines())
            self._robots_cache[origin] = parser
            return parser.can_fetch(user_agent, url)
        except HTTPError as exc:
            allowed = exc.code not in {401, 403}
            self._robots_cache[origin] = allowed
            return allowed
        except OSError:
            self._robots_cache[origin] = True
            return True


def fetch_html_page(url: str, timeout_seconds: int, user_agent: str) -> bytes:
    if not _is_http_url(url):
        raise ValueError("page URL must use http or https")
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
            "User-Agent": user_agent,
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(MAX_PAGE_BYTES + 1)
    if len(payload) > MAX_PAGE_BYTES:
        raise ValueError("HTML response exceeded 8 MB")
    return payload


def parse_job_board_page(
    payload: bytes,
    source: dict,
    page_url: str,
    *,
    max_candidates: int = 150,
) -> ParsedBoardPage:
    html = payload.decode("utf-8", errors="replace")
    preview = html[:50_000].lower()
    if any(marker in preview for marker in BLOCK_MARKERS):
        raise ValueError("the site blocked the automated HTML request")

    parser = _JobPageParser()
    parser.feed(html)
    parser.close()

    source_name = str(source.get("name") or "Job board")
    default_institution = str(source.get("institution") or "Institution not provided")
    jobs: list[JobPosting] = []
    seen_urls: set[str] = set()
    structured_count = 0
    hostname = urlparse(page_url).netloc.lower()
    use_candidate_links = True

    if hostname.endswith("jobs.ac.uk"):
        for job in _parse_jobs_ac_uk_cards(html, source, page_url):
            if job.application_url in seen_urls:
                continue
            seen_urls.add(job.application_url)
            jobs.append(job)
            structured_count += 1
    elif "academicpositions." in hostname:
        use_candidate_links = False
        for job in _parse_academic_positions_cards(html, source, page_url):
            if job.application_url in seen_urls:
                continue
            seen_urls.add(job.application_url)
            jobs.append(job)
            structured_count += 1

    for script in parser.json_ld_scripts:
        try:
            document = json.loads(script)
        except (TypeError, ValueError):
            continue
        for node in _walk_job_postings(document):
            job = _job_from_json_ld(node, source, page_url, default_institution)
            if not job or job.application_url in seen_urls:
                continue
            seen_urls.add(job.application_url)
            jobs.append(job)
            structured_count += 1

    if not use_candidate_links:
        return ParsedBoardPage(jobs, structured_count, 0)

    candidate_count = 0
    for href, anchor_text in parser.anchors:
        absolute_url = urljoin(page_url, href.strip())
        if not _is_http_url(absolute_url) or absolute_url in seen_urls:
            continue
        title = _clean_text(anchor_text)
        if _is_navigation_or_listing_link(title, absolute_url, page_url):
            continue
        detail_url = _looks_like_detail_url(absolute_url)
        if title.lower() in GENERIC_LINK_TEXT and (
            not detail_url or title.lower() not in DETAIL_FALLBACK_TEXT
        ):
            continue
        if title.lower() in GENERIC_LINK_TEXT or len(title) < 4:
            title = _title_from_url(absolute_url)
        if not title or title.lower() in GENERIC_LINK_TEXT:
            continue
        if not ROLE_TERMS.search(title):
            continue

        description = (
            f"Candidate link extracted from {source_name}. "
            "Open the source page for the full job description."
        )
        country, region = _source_geography(source, "")
        jobs.append(
            JobPosting(
                title=title,
                institution=default_institution,
                source_name=source_name,
                source_url=absolute_url,
                application_url=absolute_url,
                description_text=description,
                country=country,
                region=region,
            )
        )
        seen_urls.add(absolute_url)
        candidate_count += 1
        if candidate_count >= max_candidates:
            break

    return ParsedBoardPage(jobs, structured_count, candidate_count)


def enrich_job_from_detail_page(payload: bytes, job: JobPosting, source: dict) -> JobPosting:
    html = payload.decode("utf-8", errors="replace")
    parser = _JobPageParser()
    parser.feed(html)
    parser.close()
    default_institution = str(source.get("institution") or job.institution)
    for script in parser.json_ld_scripts:
        try:
            document = json.loads(script)
        except (TypeError, ValueError):
            continue
        for node in _walk_job_postings(document):
            detail = _job_from_json_ld(
                node,
                source,
                job.application_url,
                default_institution,
            )
            if detail:
                merge_job_postings(job, detail)
                return enrich_job_metadata(job)

    visible_text = _strip_html(html)
    if len(visible_text) > len(job.description_text):
        job.description_text = visible_text
    return enrich_job_metadata(job)


def _needs_detail_page(job: JobPosting) -> bool:
    return job.description_text.startswith("Candidate link extracted from")


class _JobPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self.json_ld_scripts: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []
        self._json_ld_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "a" and attributes.get("href"):
            self._anchor_href = attributes["href"]
            self._anchor_parts = []
        elif tag.lower() == "script" and "ld+json" in attributes.get("type", "").lower():
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._anchor_href is not None:
            self.anchors.append((self._anchor_href, " ".join(self._anchor_parts)))
            self._anchor_href = None
            self._anchor_parts = []
        elif tag.lower() == "script" and self._json_ld_parts is not None:
            self.json_ld_scripts.append("".join(self._json_ld_parts).strip())
            self._json_ld_parts = None

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_parts.append(data)
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)


class _JobsAcUkCardParser(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._depth = 0
        self._card: dict[str, object] | None = None
        self._card_depth = 0
        self._field: str | None = None
        self._field_depth = 0
        self._anchor_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in self._VOID_TAGS:
            self._depth += 1
        attributes = {name.lower(): value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())

        if tag.lower() == "div" and "j-search-result__result" in classes and self._card is None:
            self._card = {
                "href": "",
                "title_parts": [],
                "employer_parts": [],
                "department_parts": [],
                "text_parts": [],
            }
            self._card_depth = self._depth
            return
        if self._card is None:
            return
        if tag.lower() == "a" and attributes.get("href", "").startswith("/job/"):
            self._card["href"] = attributes["href"]
            self._anchor_depth = self._depth
        elif tag.lower() == "div" and "j-search-result__employer" in classes:
            self._field = "employer_parts"
            self._field_depth = self._depth
        elif tag.lower() == "div" and "j-search-result__department" in classes:
            self._field = "department_parts"
            self._field_depth = self._depth

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self._card is not None:
            if tag.lower() == "a" and self._anchor_depth == self._depth:
                self._anchor_depth = 0
            if tag.lower() == "div" and self._field_depth == self._depth:
                self._field = None
                self._field_depth = 0
            if tag.lower() == "div" and self._card_depth == self._depth:
                self.cards.append(
                    {
                        "href": str(self._card["href"]),
                        "title": _clean_text(" ".join(self._card["title_parts"])),
                        "employer": _clean_text(" ".join(self._card["employer_parts"])),
                        "department": _clean_text(" ".join(self._card["department_parts"])),
                        "text": _clean_text(" ".join(self._card["text_parts"])),
                    }
                )
                self._card = None
                self._card_depth = 0
                self._field = None
                self._field_depth = 0
                self._anchor_depth = 0
        if tag.lower() not in self._VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        self._card["text_parts"].append(data)
        if self._anchor_depth:
            self._card["title_parts"].append(data)
        if self._field:
            self._card[self._field].append(data)


class _AcademicPositionsCardParser(HTMLParser):
    _VOID_TAGS = _JobsAcUkCardParser._VOID_TAGS

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._depth = 0
        self._card: dict[str, object] | None = None
        self._card_depth = 0
        self._job_anchor_depth = 0
        self._field: str | None = None
        self._field_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in self._VOID_TAGS:
            self._depth += 1
        attributes = {name.lower(): value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())

        if tag.lower() == "div" and "job-list-item" in classes:
            self._finish_card()
            self._card = {
                "href": "",
                "title_parts": [],
                "institution_parts": [],
                "location_parts": [],
                "description_parts": [],
            }
            self._card_depth = self._depth
            return
        if self._card is None:
            return

        href = attributes.get("href", "")
        if tag.lower() == "a" and "/ad/" in href:
            self._card["href"] = href
            self._job_anchor_depth = self._depth
        elif tag.lower() == "a" and "/employer/" in href:
            self._field = "institution_parts"
            self._field_depth = self._depth
        elif tag.lower() == "div" and "job-locations" in classes:
            self._field = "location_parts"
            self._field_depth = self._depth
        elif self._job_anchor_depth and tag.lower() == "h4":
            self._field = "title_parts"
            self._field_depth = self._depth
        elif self._job_anchor_depth and tag.lower() == "p":
            self._field = "description_parts"
            self._field_depth = self._depth

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self._card is not None:
            if tag.lower() == "a" and self._job_anchor_depth == self._depth:
                self._job_anchor_depth = 0
            if self._field_depth == self._depth:
                self._field = None
                self._field_depth = 0
            if tag.lower() == "div" and self._card_depth == self._depth:
                self._finish_card()
        if tag.lower() not in self._VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._card is None or not self._field:
            return
        self._card[self._field].append(data)

    def close(self) -> None:
        super().close()
        self._finish_card()

    def _finish_card(self) -> None:
        if self._card is None:
            return
        self.cards.append(
            {
                "href": str(self._card["href"]),
                "title": _clean_text(" ".join(self._card["title_parts"])),
                "institution": _clean_text(" ".join(self._card["institution_parts"])),
                "location": _clean_text(" ".join(self._card["location_parts"])),
                "description": _clean_text(" ".join(self._card["description_parts"])),
            }
        )
        self._card = None
        self._card_depth = 0
        self._job_anchor_depth = 0
        self._field = None
        self._field_depth = 0


def _parse_jobs_ac_uk_cards(html: str, source: dict, page_url: str) -> list[JobPosting]:
    parser = _JobsAcUkCardParser()
    parser.feed(html)
    parser.close()
    jobs: list[JobPosting] = []

    for card in parser.cards:
        title = card["title"]
        url = urljoin(page_url, card["href"])
        if not title or not _is_http_url(url):
            continue
        location_match = re.search(
            r"\bLocation:\s*(.+?)(?=\s+Salary:|\s+Date Placed:|\s+Closes\b|$)",
            card["text"],
            flags=re.IGNORECASE,
        )
        location = _clean_text(location_match.group(1)) if location_match else ""
        country, region = _source_geography(source, location)
        department = card["department"]
        description = "Job card extracted from jobs.ac.uk."
        if department:
            description += f" Department: {department}."

        jobs.append(
            JobPosting(
                title=title,
                institution=card["employer"] or "Institution not provided",
                department=department,
                location=location,
                country=country,
                region=region,
                source_name=str(source.get("name") or "jobs.ac.uk"),
                source_url=url,
                application_url=url,
                description_text=description,
            )
        )
    return jobs


def _parse_academic_positions_cards(
    html: str, source: dict, page_url: str
) -> list[JobPosting]:
    parser = _AcademicPositionsCardParser()
    parser.feed(html)
    parser.close()
    jobs: list[JobPosting] = []

    for card in parser.cards:
        title = card["title"]
        url = urljoin(page_url, card["href"])
        if not title or not _is_http_url(url):
            continue
        location = card["location"]
        country, region = _source_geography(source, location)
        description = card["description"] or (
            "Job card extracted from Academic Positions."
        )

        jobs.append(
            JobPosting(
                title=title,
                institution=card["institution"] or "Institution not provided",
                location=location,
                country=country,
                region=region,
                source_name=str(source.get("name") or "Academic Positions"),
                source_url=url,
                application_url=url,
                description_text=description,
            )
        )
    return jobs


def _walk_job_postings(value: object):
    if isinstance(value, dict):
        node_type = value.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(item).lower() == "jobposting" for item in types):
            yield value
        for child in value.values():
            yield from _walk_job_postings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_job_postings(child)


def _job_from_json_ld(
    node: dict,
    source: dict,
    page_url: str,
    default_institution: str = "Institution not provided",
) -> JobPosting | None:
    title = _clean_text(str(node.get("title") or node.get("name") or ""))
    url = str(node.get("url") or "").strip()
    absolute_url = urljoin(page_url, url)
    if not title or not _is_http_url(absolute_url):
        return None

    organization = node.get("hiringOrganization")
    if isinstance(organization, dict):
        institution = _clean_text(str(organization.get("name") or ""))
    else:
        institution = _clean_text(str(organization or ""))
    location = _json_ld_location(node.get("jobLocation"))
    country, region = _source_geography(source, location)
    description = _strip_html(str(node.get("description") or ""))

    return JobPosting(
        title=title,
        institution=institution or default_institution,
        source_name=str(source.get("name") or "Job board"),
        source_url=absolute_url,
        application_url=absolute_url,
        description_text=description,
        location=location,
        country=country,
        region=region,
        date_posted=_iso_date(node.get("datePosted")),
        deadline=_iso_date(node.get("validThrough")),
    )


def _json_ld_location(value: object) -> str:
    locations = value if isinstance(value, list) else [value]
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address", location)
        if isinstance(address, str):
            return _clean_text(address)
        if not isinstance(address, dict):
            continue
        parts = [
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        rendered = ", ".join(_clean_text(str(part)) for part in parts if part)
        if rendered:
            return rendered
    return ""


def _source_geography(source: dict, location: str) -> tuple[str, str]:
    configured_country = str(source.get("country") or "")
    configured_region = str(source.get("region") or "")
    if configured_country or configured_region:
        return configured_country, configured_region

    normalized = location.lower()
    if any(term in normalized for term in ("united kingdom", "england", "scotland", "wales")):
        return "United Kingdom", "uk"
    if "canada" in normalized:
        return "Canada", "canada"
    if "australia" in normalized:
        return "Australia", "australia"
    if "hong kong" in normalized:
        return "Hong Kong", "hong_kong"
    if "singapore" in normalized:
        return "Singapore", "singapore"
    if "china" in normalized:
        return "China", "mainland_china"

    tags = {str(tag).lower() for tag in source.get("tags", [])}
    for tag, region in (
        ("us", "us"),
        ("canada", "canada"),
        ("uk", "uk"),
        ("nordics", "nordics"),
        ("europe", "eu"),
    ):
        if tag in tags:
            return "", region
    return "", ""


def _looks_like_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    if DETAIL_PATH.search(parsed.path + ("?" + parsed.query if parsed.query else "")):
        return True
    query = parsed.query.lower()
    return any(key in query for key in ("jobid=", "job_id=", "jobcode=", "vacancyid="))


def _is_navigation_or_listing_link(title: str, url: str, page_url: str) -> bool:
    normalized_title = title.lower().strip()
    if normalized_title.startswith("skip to "):
        return True
    parsed = urlparse(url)
    page = urlparse(page_url)
    if (
        parsed.netloc == page.netloc
        and parsed.path.rstrip("/") == page.path.rstrip("/")
        and parsed.fragment
    ):
        return True

    path = parsed.path.lower().rstrip("/")
    excluded_parts = (
        "/jobs/field/",
        "/jobs/country/",
        "/jobs/region/",
        "/jobs/search",
        "/job/search",
        "/post-job",
        "/post-a-job",
        "/sign-in",
        "/signin",
        "/login",
        "/register",
        "/recruiters",
        "/employers",
        "/job-alert",
        "/jobs-by-email",
    )
    return any(part in path for part in excluded_parts)


def _title_from_url(url: str) -> str:
    path = unquote(urlparse(url).path).rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"\.(?:html?|aspx?|php|cfm)$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\b\d{4,}\b", "", slug)
    return _clean_text(slug).title()


def _strip_html(value: str) -> str:
    return _clean_text(re.sub(r"<[^>]+>", " ", value))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _iso_date(value: object) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        match = re.match(r"\d{4}-\d{2}-\d{2}", text)
        return match.group(0) if match else None


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
