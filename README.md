# Activity Tracker → Daily Status Report

A standalone product that writes each person's **Daily Status Report (DSR)** from what they actually did.

- A **visible Windows tray agent** and a **Chrome/Edge extension** record which app and site is in front, and
  for how long, plus idle and locked time.
- **Google Calendar** adds meetings and calls.
- **MantisBT** adds every ticket action.
- **Gmail** (headers only) and **Drive** add email and document work.
- A **local LLM** (Ollama, mistral-nemo:12b) summarises everything item by item, writes the report and gives
  suggestions. **Code computes every number; the model only writes the text, and guards check it.**
- The person reviews and submits the report. The manager gets it by email, in the Team view, in Excel and PDF,
  and in the company's own Excel template.

Plan and decisions: [docs/plan.md](docs/plan.md).

## What each screen does

| Screen | Who | What |
|---|---|---|
| **My day** | everyone | Key numbers, *where the 9 hours went* (always adds up to the shift), timeline with meetings, hour-by-hour, focus and switching, top apps/sites, meetings (confirm "did you attend?"), work output, and the AI report: edit, remove tasks, preview what the manager sees, submit, export (Excel, PDF, company template) |
| **Analysis** | everyone; managers pick a person | 7/30-day trend, productive-time heatmap by hour, day-by-day table, AI week and month summaries |
| **Team** | managers (own teams), admins | One row per person (shift bar, worked, productive, meetings, focus, overtime, tickets, emails, report status), AI team summary, team Excel; open anyone's day read-only (audited) |
| **Downloads** | everyone | Setup code, Windows agent, browser extension, what is and isn't recorded |
| **Account** | everyone | Change password, Google connection (per-person mode) |
| **Admin** | admins | People & teams (shift/break/manager, PCs, setup codes, password reset, Mantis/Google identity) · Category rules + AI rule suggestions · Integrations (AI, Google, Mantis, email, retention, shared folder, sync now) · Excel template (upload, map cells/columns, preview, activate) |

## How the report is built

1. **Sessions** (`app/pipeline`): spans from the agent are split per local day. Overlaps are never counted
   twice, and the same app or site is merged across gaps of 30 s or less. Admin rules then give each session
   a category.
2. **Analysis** (`app/analysis/engine.py`): every second of the day gets one label, so the shift breakdown
   always sums to the shift. It covers:
   - meetings: attended, confirmed, multitasking, unclear (asked) or not attended
   - calls that weren't on the calendar
   - the break (the longest away stretches first)
   - overtime, focus blocks, switching, time sinks, meeting load
   - comparison with the person's usual days and with the team
3. **Blocks** (`app/dsr/blocks.py`): productive time grouped per ticket, document, repository or app.
4. **AI levels** (`app/ai/levels.py`):
   - item (each ticket, email thread, document, meeting, work block)
   - section (tickets, email, documents, meetings, focus)
   - day report (the model groups productive blocks into tasks; email and chat, meetings, and admin are
     standard tasks)
   - suggestions (the model picks among observations measured by code)
   - team day
   - week and month
5. **Guards** (`app/ai/guards.py`): every number must come from the facts, and every `#ticket` must exist.
   Failures are retried with the errors, then repaired (the offending sentence is dropped), then replaced by
   text written by code. The report is always produced, and its `ai_status` says which of these happened.
   Item summaries are cached by content, so the end-of-day run is fast (15–40 s per person on the 1080 Ti).

## Run

```powershell
scripts\setup.ps1                 # first time: venv, private Postgres :5546, .local\.env, migrations, default rules
scripts\dev-up.ps1                # Postgres :5546, API :8040 (local only), worker, web :3030
scripts\dev-down.ps1              # stop (-KeepDb leaves Postgres running)
scripts\build-downloads.ps1 -Server http://192.168.5.109:3030   # agent .exe + extension .zip for Downloads
```

Open **http://192.168.5.109:3030** (or http://localhost:3030 on the server). The admin password is in
`.local\secrets\admin-credentials.txt`. After changing the UI, run `npm run build` in `apps\web` (or start
with `dev-up.ps1 -DevWeb`).

```powershell
cd apps\api
..\..\.venv\Scripts\python -m app.cli demo          # demo team "Demo Support": 3 people, 7 days (passwords in .local\secrets\demo-users.txt)
..\..\.venv\Scripts\python -m app.cli demo-remove   # delete all demo and e2e people and data
..\..\.venv\Scripts\python -m app.cli create-admin <email> <name> [--password-file <path>]
```

## Configure (Admin → Integrations)

- **AI:** Ollama address and model, plus a "Test the model" button. If it is switched off or unreachable,
  reports are still written by code.
- **Google:**
  - *Service account* (Google Workspace, recommended): upload the key and allow its client ID the scopes
    `calendar.readonly`, `gmail.metadata` and `drive.activity.readonly` in the Admin console (domain-wide
    delegation).
  - *Each person connects*: needs an OAuth client, and the site on **https** (Google rejects http redirects
    except for localhost).
  - Managers see email counts, not subjects, unless you allow subjects.
- **MantisBT:** set the address and turn sync on. The API token is read from the **`TRACKER_MANTIS_TOKEN`
  environment variable** on the server (set it yourself, then restart with `dev-up.ps1`); it is never stored in
  the database. People are matched by their Mantis username (Admin → People → Edit), else by email.
- **Email:** SMTP server, sender address, send time (each team's local time), whether to send drafts nobody
  submitted (marked "not reviewed"), and Excel/PDF attachments. "Send test" checks it.
- **Reports and data:** when drafts are written after the shift ends, how long raw activity is kept (default
  30 days), the privacy notice, a shared folder for daily Excel files, and a master workbook per team.

## Background worker (`python -m app.worker`, started by dev-up)

| Job | When |
|---|---|
| Rebuild today's sessions and analysis | every 5 min |
| Google + Mantis sync; summaries for new items | every 30 min |
| Final sync, then the AI draft of each DSR | 15 min after each person's shift ends (configurable) |
| Team summary | 30 min after that |
| Email to managers (copy to the person), team digest, master workbook, shared folder | the configured send time |
| Delete old raw events; AI category suggestions for unknown sites | nightly 02:00 |
| Week summaries (Mondays), month summaries (1st) | 03:00 |

Each job runs once per key (`job_runs`), even across restarts. Logs are in `.local\logs\worker.err.log`.

## Tests

```powershell
cd apps\api; ..\..\.venv\Scripts\python -m pytest -q    # 69 tests: pipeline, analysis, AI guards, integrations (recorded APIs), exports, worker, access
cd agent;    ..\.venv\Scripts\python -m pytest -q       # 16 tests: sampling logic, outbox, local listener origin check
cd apps\web; npm run e2e                                 # Playwright against the running stack (uses the real local model)
```

## Privacy and access

- **Never recorded:** screenshots, keystrokes, the clipboard, page contents, incognito windows, or any detail
  while paused or in Private mode.
- **Gmail** is read as headers only.
- **Who sees what:** everyone sees their own data; managers see the teams they manage; admins see everyone.
  Every view of someone else's day, trend or export is in `audit_log`.
- **Suggestions** are shown only to the person, never to managers.

## Known limitations

- The agent is not code-signed (Windows SmartScreen warns), and the extension is installed in developer mode.
- Excel templates lose any charts or pictures inside them (a limit of openpyxl). Cells, styles, formulas and
  other sheets are kept.
- Per-person Google connection needs https. The service-account mode needs Google Workspace.
- Idle starts after 5 minutes without input, so the minutes before that count as the last activity.
