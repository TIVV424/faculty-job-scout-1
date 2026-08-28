from faculty_job_scout.sources.job_boards import JobBoardsAdapter, parse_job_board_page


SOURCE = {
    "name": "Example Academic Board",
    "url": "https://jobs.example.edu/search",
    "tags": ["us", "engineering"],
}


def test_parse_json_ld_and_candidate_links() -> None:
    payload = b"""<html><head>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"JobPosting",
       "title":"Assistant Professor in Energy Systems",
       "url":"/job/energy-systems-42",
       "hiringOrganization":{"name":"Example University"},
       "jobLocation":{"address":{"addressLocality":"Boston",
         "addressRegion":"MA","addressCountry":"United States"}},
       "datePosted":"2026-06-19","validThrough":"2026-08-01T23:59:00Z",
       "description":"Research in &lt;b&gt;optimization&lt;/b&gt; and control."}
      </script></head><body>
      <a href="/position/lecturer-transport">Lecturer in Transportation</a>
      <a href="/about">About us</a>
    </body></html>"""

    parsed = parse_job_board_page(payload, SOURCE, SOURCE["url"])

    assert parsed.structured_jobs == 1
    assert parsed.candidate_links == 1
    assert len(parsed.jobs) == 2
    assert parsed.jobs[0].institution == "Example University"
    assert parsed.jobs[0].deadline == "2026-08-01"
    assert parsed.jobs[1].title == "Lecturer in Transportation"


def test_candidate_link_fallback_uses_url_slug() -> None:
    payload = b'<html><a href="/jobs/assistant-professor-electric-mobility-12345">Apply</a></html>'

    parsed = parse_job_board_page(payload, SOURCE, SOURCE["url"])

    assert len(parsed.jobs) == 1
    assert parsed.jobs[0].title == "Assistant Professor Electric Mobility"
    assert parsed.jobs[0].institution == "Institution not provided"


def test_candidate_link_uses_configured_institution_when_available() -> None:
    source = {
        **SOURCE,
        "institution": "Eindhoven University of Technology",
        "country": "Netherlands",
        "region": "eu",
    }
    payload = b'<html><a href="/jobs/assistant-professor-electric-mobility-12345">Apply</a></html>'

    parsed = parse_job_board_page(payload, source, SOURCE["url"])

    assert len(parsed.jobs) == 1
    assert parsed.jobs[0].institution == "Eindhoven University of Technology"
    assert parsed.jobs[0].country == "Netherlands"
    assert parsed.jobs[0].region == "eu"


def test_navigation_and_category_links_are_not_jobs() -> None:
    payload = b"""<html>
      <a href="/jobs/field/machine-learning">Machine Learning 290</a>
      <a href="/jobs/engineering-and-mathematics">Engineering &amp; Mathematics</a>
      <a href="/jobs#listing">Skip to job results</a>
      <a href="/post-job">Post a Job</a>
      <a href="/sign-in">2026 Global Faculty Recruitment</a>
      <a href="/job/assistant-professor-control">Assistant Professor in Control</a>
    </html>"""

    parsed = parse_job_board_page(payload, SOURCE, "https://jobs.example.edu/jobs")

    assert [job.title for job in parsed.jobs] == ["Assistant Professor in Control"]


def test_normal_page_script_may_mention_captcha() -> None:
    payload = b"""<html><head><script>const captchaEnabled = true;</script></head>
      <body><a href="/job/lecturer-energy">Lecturer in Energy</a></body></html>"""

    parsed = parse_job_board_page(payload, SOURCE, SOURCE["url"])

    assert [job.title for job in parsed.jobs] == ["Lecturer in Energy"]


def test_jobs_ac_uk_card_extracts_employer_department_and_location() -> None:
    payload = b"""<html><body>
      <div class="j-search-result__result" data-advert-id="1077316">
        <div class="j-search-result__text">
          <a href="/job/DRT764/lecturers-in-computer-science">Lecturers in Computer Science</a>
          <div class="j-search-result__department">School of Computer Science</div>
          <div class="j-search-result__employer"><b>University of Leeds</b></div>
          <div>Location: Leeds</div>
          <div class="j-search-result__info"><strong>Salary:</strong> GBP 51,753</div>
          <div><strong>Date Placed:</strong> 18 Jun</div>
        </div>
        <div class="j-search-result__date-logos"><div>Closes 30 Jun</div></div>
      </div>
    </body></html>"""
    source = {
        "name": "jobs.ac.uk Computer Sciences",
        "url": "https://www.jobs.ac.uk/search/computer-sciences",
        "tags": ["uk", "europe", "computer_science"],
    }

    parsed = parse_job_board_page(payload, source, source["url"])

    assert len(parsed.jobs) == 1
    assert parsed.structured_jobs == 1
    assert parsed.candidate_links == 0
    assert parsed.jobs[0].institution == "University of Leeds"
    assert parsed.jobs[0].department == "School of Computer Science"
    assert parsed.jobs[0].location == "Leeds"
    assert parsed.jobs[0].region == "uk"


def test_academic_positions_card_extracts_job_not_filters() -> None:
    payload = b"""<html><body>
      <a href="https://academicpositions.com/jobs/position/tenure-track/country/finland">
        Finland
      </a>
      <div class="card shadow-sm mb-4 job-list-item">
        <div class="card-body">
          <a href="https://academicpositions.com/employer/university-of-oulu"
             class="text-reset job-link">University of Oulu</a>
          <div class="job-locations">
            <a href="https://academicpositions.com/jobs/country/finland/oulu">Oulu, </a>
            <a href="https://academicpositions.com/jobs/country/finland">Finland</a>
          </div>
          <a href="/ad/university-of-oulu/2026/tenure-track-assistant-professor/250080"
             class="text-dark job-link">
            <h4>Tenure Track Assistant Professor in Applied Geophysics</h4>
            <p class="text-muted">Research and teaching in applied geophysics.</p>
          </a>
        </div>
      </div>
    </body></html>"""
    source = {
        "name": "Academic Positions",
        "url": "https://academicpositions.com/jobs/position/tenure-track?page=1",
        "tags": ["global", "europe", "faculty", "tenure_track"],
    }

    parsed = parse_job_board_page(payload, source, source["url"])

    assert len(parsed.jobs) == 1
    assert parsed.structured_jobs == 1
    assert parsed.candidate_links == 0
    assert parsed.jobs[0].title == "Tenure Track Assistant Professor in Applied Geophysics"
    assert parsed.jobs[0].institution == "University of Oulu"
    assert parsed.jobs[0].location == "Oulu, Finland"
    assert parsed.jobs[0].application_url == (
        "https://academicpositions.com/ad/university-of-oulu/2026/"
        "tenure-track-assistant-professor/250080"
    )


def test_adapter_isolates_failures_and_respects_robots() -> None:
    sources = [
        {"name": "Working", "url": "https://working.example/jobs"},
        {"name": "Blocked by robots", "url": "https://robots.example/jobs"},
        {"name": "Broken", "url": "https://broken.example/jobs"},
    ]
    sleeps: list[float] = []

    def fetcher(url: str, timeout: int, user_agent: str) -> bytes:
        if "broken" in url:
            raise TimeoutError("timed out")
        return b'<a href="/job/open-rank-faculty">Open-rank faculty in engineering</a>'

    adapter = JobBoardsAdapter(
        sources,
        delay_seconds=1.5,
        max_detail_pages_per_source=0,
        fetcher=fetcher,
        robots_checker=lambda url, user_agent: "robots.example" not in url,
        sleeper=sleeps.append,
    )

    result = adapter.collect()

    assert len(result.jobs) == 1
    assert sleeps == [1.5]
    assert any("disallows" in warning for warning in result.warnings)
    assert any("timed out" in warning for warning in result.warnings)


def test_adapter_enriches_candidate_from_detail_json_ld() -> None:
    source = {"name": "Board", "url": "https://board.example/jobs", "region": "us"}

    def fetcher(url: str, timeout: int, user_agent: str) -> bytes:
        if url == source["url"]:
            return b'<a href="/job/energy-systems">Assistant Professor in Energy Systems</a>'
        return b"""<html><script type="application/ld+json">{
          "@type": "JobPosting",
          "title": "Assistant Professor in Energy Systems",
          "url": "https://board.example/job/energy-systems",
          "hiringOrganization": {"name": "Example University"},
          "description": "Department: Department of Mechanical Engineering. EV charging."
        }</script></html>"""

    adapter = JobBoardsAdapter(
        [source],
        delay_seconds=0,
        fetcher=fetcher,
        robots_checker=lambda url, user_agent: True,
    )

    result = adapter.collect()

    assert len(result.jobs) == 1
    assert result.jobs[0].institution == "Example University"
    assert result.jobs[0].department == "Department of Mechanical Engineering"
    assert "EV charging" in result.jobs[0].description_text
