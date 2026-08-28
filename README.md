# Faculty Job Scout

Faculty Job Scout is a configurable Python tool for finding and ranking academic
vacancies. It collects postings from HTML job boards and RSS feeds, enriches sparse
records from detail pages, removes duplicates, scores fit, and produces a weekly digest.
A failing source is reported without stopping the other sources.

Vibe-coded. 

## What it can do

- Collect live vacancies from multiple job boards and optional RSS feeds.
- Track individual vacancy URLs for inclusion in the local run summary.
- Rank jobs with transparent keyword, role, institution, and region weights.
- Optionally use the OpenAI Responses API for structured, evidence-based scoring.
- Merge duplicate postings while retaining the most complete metadata.
- Store results in SQLite and CSV and write a readable Markdown run summary.
- Send an HTML email digest through Gmail SMTP.
- Run manually on a computer or automatically with GitHub Actions.

The files in `config/` contain generic examples. Replace them before relying on the
rankings. See [Configuration](config/README.md) for every active setting.

## Local setup

Python 3.11 or newer is required. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
```

Edit `config/profile.yaml`, `config/keywords.yaml`, `config/institutions.yaml`, and
`config/sources.yaml`. Then run the bundled demonstration without network access,
API calls, or email:

```powershell
python -m faculty_job_scout.main --dry-run --no-email
```

To collect configured live sources while still suppressing LLM calls and email:

```powershell
python -m faculty_job_scout.main --dry-run --no-email --live-sources
```

Generated SQLite, CSV, and Markdown files are written under `data/` and ignored by Git.

### Optional local secrets

The program reads secrets from environment variables; it does not read `.env` files
automatically. Set only the services you enable:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:GMAIL_SENDER_EMAIL="sender@gmail.com"
$env:GMAIL_APP_PASSWORD="your-gmail-app-password"
$env:NEWSLETTER_RECIPIENT_EMAIL="recipient@example.com"
```

Use a Gmail app password rather than the account password. Test each external service
independently before a full run:

```powershell
python -m faculty_job_scout.main --test-llm
python -m faculty_job_scout.main --test-email
python -m faculty_job_scout.main --once
```

The default `gpt-5.6-luna` model is intended for cost-sensitive workloads and supports
structured outputs through the Responses API. Change `openai.model` in
`config/settings.yaml` if another model better fits your quality and cost needs. See the
[official OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

## GitHub setup

GitHub is optional. Use it when you want a hosted repository, scheduled execution, and
downloadable CSV artifacts.

1. Create an empty GitHub repository, then publish this folder:

   ```powershell
   git init
   git add .
   git commit -m "Initial public version"
   git branch -M main
   git remote add origin https://github.com/YOUR-ACCOUNT/faculty-job-scout.git
   git push -u origin main
   ```

2. Under **Settings > Secrets and variables > Actions**, add the secrets needed by the
   modes you plan to use:

   | Secret | Required for |
   | --- | --- |
   | `OPENAI_API_KEY` | `llm-test` and LLM scoring during `full-run` |
   | `GMAIL_SENDER_EMAIL` | `email-test`, `full-run`, and scheduled runs |
   | `GMAIL_APP_PASSWORD` | `email-test`, `full-run`, and scheduled runs |
   | `NEWSLETTER_RECIPIENT_EMAIL` | `email-test`, `full-run`, and scheduled runs |

3. Open **Actions > Faculty Job Scout > Run workflow**. Start with `collect-only`,
   download its CSV artifact, then try `llm-test`, `email-test`, and `full-run` as needed.

4. Review the cron expression in `.github/workflows/faculty_job_scout.yml`. GitHub cron
   uses UTC. Commit a schedule change if the default Friday 14:00 UTC run is unsuitable.

Never commit credentials, a populated `.env`, generated databases, CSV exports, or raw
scraped pages. Forks do not receive the original repository's Actions secrets.

## Commands

| Command | Effect |
| --- | --- |
| `python -m faculty_job_scout.main --dry-run --no-email` | Score bundled demonstration jobs locally |
| `python -m faculty_job_scout.main --dry-run --no-email --live-sources` | Collect live sources without LLM or email |
| `python -m faculty_job_scout.main --test-llm` | Score one built-in posting with the configured model |
| `python -m faculty_job_scout.main --test-email` | Send one Gmail formatting and credential test |
| `python -m faculty_job_scout.main --once` | Collect, score, persist, summarize, and email once |
| `faculty-job-scout ...` | Use the installed console command with the same options |

Add `--config-dir PATH` to use a different configuration folder and `--log-level DEBUG`
for detailed diagnostics.

## How a run works

1. Enabled sources return candidate postings.
2. Detail pages fill missing institution, department, description, and deadline fields.
3. Duplicate URLs and similar title/institution pairs are consolidated.
4. Rule scoring applies the values in `keywords.yaml`, `institutions.yaml`, and
   `settings.yaml`.
5. Eligible postings are optionally rescored by the configured OpenAI model.
6. SQLite, CSV, Markdown, and optional email outputs are produced.

## Current limitations

- Job-board HTML changes can reduce extraction quality until the relevant parser is updated.
- `official_pages` supplies demonstration data for dry runs; live official-page scraping is
  not implemented in this version.
- The included Notion code is a mock integration and is not exposed as a supported output.
- Region and deadline detection are heuristic when a source omits structured metadata.

Run `pytest` after configuration-independent code changes.
