# Configuration

All personal preferences belong in this directory. The committed files are generic examples
and contain no credentials. YAML indentation matters; run `pytest` after editing structure.

## Files

| File | What to customize |
| --- | --- |
| `profile.yaml` | Candidate summary, methods, domains, and themes sent to the optional LLM scorer |
| `keywords.yaml` | High-value, medium-value, and negative terms used by rule scoring |
| `institutions.yaml` | Institutions that receive the configured priority bonus, including aliases |
| `sources.yaml` | Enabled job boards, RSS feeds, demonstration pages, and tracked vacancies |
| `settings.yaml` | Scoring weights, regions, outputs, email, OpenAI, scraping, and deduplication |
| `email_template.md` | Digest headings and placeholder locations |

## Profile, keywords, and institutions

`profile.yaml` affects LLM scoring only. Keep the summary factual and make the interest lists
specific enough to distinguish a real match from a generic academic vacancy.

`keywords.yaml` affects rule scoring. Each distinct high- or medium-value term adds the weight
defined in `settings.yaml`, up to its corresponding maximum. Negative terms subtract points.
Use phrases when a single word is ambiguous.

`institutions.yaml` is optional. Leave `priority_universities` empty for no prestige or
watchlist bonus. Aliases must be explicit because matching is normalized but not fuzzy.

## Sources

Each `job_boards.sources` entry accepts `name`, `url`, `source_type`, `priority`, and `tags`.
Optional `institution`, `country`, and `region` values fill metadata that the page may omit.
Set `job_boards.enabled` to `false` to disable all HTML boards.

RSS entries use the same metadata shape under `rss.feeds`. Set `rss.enabled` to `true` after
adding feeds. `target_positions.positions` accepts `name`, `url`, `title`, `institution`, and
`note`; these positions are checked in the Markdown summary. They are not a separate scraper.

The built-in dry run uses demonstration postings when `official_pages.enabled` is `true`.
The `official_pages.pages` list is reserved for a future live adapter.

## Settings

### Newsletter and deadlines

- `newsletter.include_categories_main`: score bands placed in the main digest.
- `include_category_c_if_priority_institution`: includes C jobs from the watchlist.
- `include_category_d`: includes the lowest score band.
- `subject_template`: supports `{num_new}` and `{num_strong}`.
- `max_jobs_per_section`: limits email length.
- `deadline_reminders.*_window_days`: controls reminder and urgent sections.

Fit categories are A (75-100), B (55-74), C (35-54), and D (0-34).

### Regions

Each boolean under `regions.include` allows or excludes the normalized region. An excluded or
unknown region receives `scoring.excluded_region_penalty`. Add a key if a source emits another
normalized region name.

### Scoring

- `role_weights`: starting score for each detected role type.
- `*_per_hit` and `max_*_bonus`: keyword contribution and cap.
- `tenure_bonus`: extra weight for explicit tenure language.
- `priority_institution_bonus`: watchlist bonus.
- `included_region_bonus` and `excluded_region_penalty`: region adjustment.
- `negative_per_hit` and `max_negative_penalty`: negative keyword adjustment.
- `part_time_penalty`: adjustment for part-time postings.
- `lower_priority_score_cap`: maximum final score for part-time postings.

Weights are fractions of the final 0-100 score and the total is clipped to 0-1 before
conversion. For example, `0.10` means ten points.

### Outputs

Each SQLite, CSV, and Markdown output has `enabled` and `path`. Relative paths are resolved
from the project directory. SQLite retains history for deduplication; CSV and Markdown are
convenient review outputs.

### Email and OpenAI

`email.enabled` controls delivery during `--once`; host, port, and TLS settings configure SMTP.
Credentials always come from the three Gmail environment variables listed in the main README.

`openai.enabled` controls LLM scoring during non-dry runs. `model` selects the API model,
`api_key_env_var` names the environment variable, and `min_rule_score_for_llm` prevents API
spend on weak prescreen matches. API failures fall back to the rule score.

### Scraping and deduplication

- `request_timeout_seconds`: per-request network timeout.
- `delay_between_requests_seconds`: pause between requests to the same adapter.
- `respect_robots_txt`: honor disallow rules before fetching detail pages.
- `max_detail_pages_per_source`: cap on detail-page requests per source and run.
- `fuzzy_title_threshold` and `fuzzy_institution_threshold`: duplicate similarity thresholds
  from 0 to 1; higher values require closer matches.

The GitHub schedule is intentionally not duplicated in YAML configuration. Change the cron
expression in `.github/workflows/faculty_job_scout.yml`; GitHub interprets it in UTC.
