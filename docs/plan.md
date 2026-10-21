# Plan: Agentic AI Activity Tracker → Daily Status Report (DSR)

## Context
Managers need a Daily Status Report (DSR) for each resource without people writing it by hand. The system
records what each person works on (which app, which site, for how long), and a local AI agent groups that
activity into tasks, summarises it and writes the DSR. The person reviews it before it goes to the manager.

Decisions taken:
- Capture with a **Windows tray agent + Chrome/Edge extension**.
- Tracking is **visible**: tray icon, Pause/Private mode, and the person reviews their own DSR first.
- AI is **local Ollama** (mistral-nemo:12b, as in DMT), so no activity data leaves the network.
- Delivery: **web dashboard + end-of-day email + PDF/Excel export**.
- **Google Calendar** calls and meetings are included in the DSR.
- **Excel**: the system makes its own DSR workbook **and** fills the company's existing DSR template.
- **Workday**: 9 hours (for example 09:00–18:00) including a 1 hour break, so 8 hours of expected work.
  Every day is analysed against this.

This is a **separate, standalone product** in its own repository, `D:\Projects\activity-tracker`. It has its
own database, users, configuration and Google OAuth app. It does not import, call or depend on LaunchOps
or any other project. The only thing it has in common with them is the stack: FastAPI + SQLAlchemy +
Alembic + Postgres, Next.js 15 + Tailwind, Playwright, with `scripts\dev-up.ps1` to start it.
Ports: API **8040**, web **3030**, Postgres **5546** (8020/3010/5544, 8030/3020/5545 and 3000 are taken).

## Status (2026-10-22): all steps built
Steps A, B and 4–9 are done:
- Admin (people and teams, rules, integrations, Excel template)
- My Day, Analysis, Team
- 9-hour analysis engine
- Google Calendar, Gmail and Drive sync, and MantisBT sync
- AI levels with number and ticket guards
- Excel (own workbook, company template, master workbook), PDF and email
- the worker
- demo data and the Playwright e2e tests

Tests: API 69, agent 16, e2e 4 (with the real local model). Still open:
- the Google and Mantis credentials, which the user provides
- SMTP settings
- code-signing the agent, and installing the extension through policy
- a git commit

## Progress (as of 2026-10-22, before the rest was built)
**Done** (`D:\Projects\activity-tracker`; 28 API tests and 16 agent tests passing):
- Step 1: database and migrations, login and roles, teams with shift and break, linking PCs with one-time
  setup codes, receiving activity (`/ingest`, gzip, no double counting), working out sessions, rule categories.
- Step 2: Windows tray agent (`ActivityTrackerAgent.exe` 0.1.1). Pause and Private mode, local outbox so
  nothing is lost offline, device key in Credential Manager, starts with Windows.
- Step 3: Chrome/Edge extension 0.1.1. Fixed ID, reports only to the local agent, never incognito, popup that
  explains what to do when the agent isn't running.
- Web: sign-in, Downloads (setup code, agent, extension, what is recorded), Account (change password).
- Network: firewall rule for port 3030 on the local subnet. Server is http://192.168.5.109:3030 (SER-022).
  The admin account is attashah70@gmail.com.

**Open items from steps 1–3:**
- Confirm on a real desktop PC that the agent tracks activity and the extension shows green. This server has
  no interactive desktop, so that couldn't be tested here.
- If the extension still can't reach a running agent, check Chrome's Local Network Access restrictions.
- No git commit has been made yet.
- Later: code-sign the agent (to remove the Windows SmartScreen warning), and install the extension through
  company policy instead of developer mode.

## Pending, in recommended order
- **A. Admin: Users and Teams screen.** Brought forward because right now people can only be added through the
  API, so nobody else can sign in to set up their PC. It covers creating, editing and disabling people;
  resetting a password (the new one is shown once); setting team, manager, shift and break; and seeing each
  person's linked PCs (last seen, revoke). Uses the existing `/admin/*` endpoints plus new edit, disable,
  reset and devices endpoints.
- **B. My Day (first version).** The day's timeline and time by category, app and site, from
  `GET /me/days/{date}`, so collected data can be seen and checked straight after rollout.
- **Step 4.** AI DSR draft with Ollama mistral-nemo, including the check, the retries and the rule-only fallback.
- **Step 5.** The 9-hour analysis: where the hours went (adding up to exactly 9:00), time sinks, focus,
  hourly heatmap, meeting load.
- **Step 6.** Google Calendar meetings and calls. This needs a Google Cloud OAuth client, or domain-wide
  delegation, set up by you.
- **Step 6b.** Mantis ticket actions and time per ticket (the user sets `TRACKER_MANTIS_TOKEN`), Gmail
  counts, Drive activity.
- **Step 6c.** AI on every output: item, section, day, suggestions, team and week summaries, with the number
  and reference checks.
- **Step 7.** The rest of the web app: full My Day (review, edit, submit), Analysis, Team view for managers,
  and the rest of Admin (rules, AI rule suggestions, Calendar, Excel template).
- **Step 8.** Excel (own workbook, company template, master workbook), PDF, end-of-day email, cleanup of old
  raw data.
- **Step 9.** Demo data, docs, Playwright E2E.

## Architecture
```
[Windows agent (Python, tray)] --+
                                  +--> POST /ingest (device token, batched, gzip) --> Postgres
[Browser extension (MV3)] -------+        |
                                          v
              worker: sessionise -> categorise -> AI agent -> DSR draft
                                          |
              web: My Day (review/edit/submit) | Manager team view | Admin rules | email | export
```

## Components

### 1. Windows agent — `agent/` (Python, built into an .exe with PyInstaller)
- Every 5 s: foreground window via `win32gui.GetForegroundWindow`, process name (`psutil`), window title,
  idle seconds via `GetLastInputInfo` (idle if more than 5 min, configurable).
- Writes samples to a local SQLite queue and sends them every 60 s, so data survives a network outage.
- Tray icon (`pystray`): "Tracking on", **Pause** (15/30/60 min), **Private mode** (records only "Private"
  with no details), "Open My Day".
- Registers once with an enrolment code from the admin and stores a device token in Windows Credential Manager.
- Starts with Windows (shortcut in the Startup folder). It is not hidden and the person can see it running.

### 2. Browser extension — `extension/` (Chrome/Edge Manifest V3)
- `tabs.onActivated`, `tabs.onUpdated` and `windows.onFocusChanged` record the active tab's domain, path and title.
- `chrome.idle` records idle and locked time.
- Sends events to the local agent on `http://127.0.0.1:<port>`, so the extension needs no login of its own.
  The agent merges them with its window samples: when the foreground app is a browser, the extension's URL is used.
- Settings: domain blocklist (domain only, never the path, e.g. for banking) and incognito tabs are never tracked.

### 3. API — `apps/api` (FastAPI)
Tables (Alembic): `orgs, users, teams, devices, raw_events (partitioned by day), sessions, categories,
category_rules, dsr_reports, dsr_items, audit_log, settings`.
- `POST /ingest/events`: device-token auth, idempotent by `(device_id, seq)`.
- **Sessioniser**: merges consecutive samples with the same app and domain into sessions, ignores gaps under
  30 s, and splits idle time into separate sessions.
- **Rule categoriser** (deterministic, runs first): admin rules such as `github.com → Development/Productive`,
  `youtube.com → Non-work`, `*.mantis* → Ticket work`. Each session gets a category and a productivity class.
- Auth: email + password with roles `resource`, `manager`, `admin`. A manager only sees their own team.
- Retention job: raw events are deleted after N days (default 30). Sessions and DSRs are kept.

### 4. Agentic DSR pipeline — `apps/api/app/agent/` (Ollama, tool-calling loop)
The worker runs at the end of each person's day (configured time, or when the person clicks "Generate").
Code computes every number and the model only writes the text, so the model cannot invent time (this follows
the DMT rule that the AI plans and code executes).
1. **Group**: code clusters sessions into work blocks (same project keyword, ticket number such as `#12345`,
   repository or document title).
2. **Agent loop**: the model gets the blocks and these tools: `get_sessions(block)`, `lookup_ticket(id)`
   (Mantis), `get_category(domain)`, `get_yesterday_dsr()`, `get_work_actions(block)`, `get_meetings()` and
`get_day_analysis()`. It returns JSON
   `{tasks:[{title, block_ids, category, summary, status}], highlights, blockers, tomorrow}`.
3. **Validate**: a Pydantic schema check. Every block must be assigned to exactly one task, and task minutes
   are recalculated by code from `block_ids`. If the output is invalid, the model is asked again (up to 2 times).
   If it still fails, a DSR is built from the rule categories only, and the DSR is marked "AI unavailable".
4. **Suggest rules**: domains with no category are sent to the model for a suggested category, which goes to an
   admin queue. Nothing is applied automatically.
5. Result: `dsr_reports` in state `draft`, then `submitted` (by the person), then `sent`.

### 4a. Google Calendar calls — `apps/api/app/integrations/gcal.py`
- Each user connects with Google OAuth (scope `calendar.readonly`). The admin can instead set up domain-wide
  delegation with a service account, so nobody has to connect one by one. The project uses its own Google
  Cloud OAuth client, written from scratch.
- At the end of each day (and every 30 min during the day) the worker pulls that day's events. It skips
  declined events, all-day events and events marked free, and stores them in `calendar_events`
  (title, start and end, attendee count, whether it has a Meet link, organiser).
- **Merge with activity**: the meeting time is counted as **Meeting/Call**.
  - Confirmed attended: a Meet tab or the Meet app was active, or the PC was idle or locked (a phone or room call).
  - Possibly skipped: the person was in unrelated apps for the whole slot, so the meeting is flagged
    "attended? (please confirm)" in My Day.
  - Multitasking: a short meeting with heavy other activity is shown in the analysis as "Meeting + Development".
  - Calls not on the calendar: a Meet, Zoom or Teams window with no calendar event is counted as an
    ad-hoc call.
- In the DSR, meetings get their own section (time, title, duration, attendees), and the AI uses meeting
  titles when it names tasks.

### 4a-2. Work output: every action counted — `apps/api/app/integrations/{mantis,gmail,gdrive}.py`
Every action from every source goes into one table, `work_actions`, with the fields
`(user, source, action, object_id, object_title, at, meta)`. The DSR and the analysis read from that table.
- **MantisBT** (REST API; the token is read from env var `TRACKER_MANTIS_TOKEN`, which the user sets, and is
  never stored in the repo):
  - The worker fetches issues updated today, then each issue's notes and history, and credits each action to
    the user who did it. Actions: **reported, assigned or taken, note or response added, status changed,
    resolved, closed, reopened, file attached**. Mantis users are matched to tracker users by email
    (an admin can override the match).
  - **Time per ticket**: browser URLs such as `view.php?id=12345` give the real time spent on each ticket
    page, so the DSR can say, for example, "#12345 (40 min): replied, moved to Resolved".
- **Gmail** (scope `gmail.metadata`, so headers only and never message bodies): emails **sent**,
  **replies** (In-Reply-To), **new threads started**, and **distinct threads handled**, with the main
  recipient domains (for example "6 replies to client X"). Subjects are shown only to the person themselves,
  unless the admin turns on showing them to managers.
- **Google Docs/Sheets/Slides** (Drive Activity API, `drive.activity.readonly`): files **created**,
  **edited**, **commented on** and **shared**, with the file name and type. Time spent in each document
  comes from the browser.
- **Meetings and calls**: from 4a, the count and total duration.
- All Google sources use the same per-user OAuth or domain-wide delegation as the Calendar integration.
- The DSR gets a **"Work Output"** section, for example: *Tickets: 3 reported · 11 responded ·
  4 resolved · 1 reopened | Emails: 18 sent (12 replies) across 9 threads | Docs: 2 created, 5 edited |
  Meetings: 4 (2h10m)*, followed by the full list of actions. The AI uses ticket and document titles to
  name tasks and links each task to its actions.
- The analysis adds **output per productive hour**, trends for each count, and a comparison with the
  team average.

### 4b. 9-hour day analysis — `apps/api/app/analysis/`
Code computes every number for each person and day, against the shift (default 09:00–18:00 with a 60 min break):
- **Where the 9 hours went** (adds up to exactly 9:00): Productive work · Meetings/Calls · Communication
  (email, chat) · Neutral/Admin · Non-work · Idle at desk · Break · Away/untracked. Time before or after
  the shift is shown separately as overtime.
- **Time sinks**: top 10 apps and sites by time, and the longest sessions of non-productive or neutral time.
- **Focus quality**: longest unbroken focus block, number of focus blocks over 25 min, context switches per hour.
- **Hour-by-hour heatmap**: what share of each hour went to each category.
- **Meeting load**: % of the day in meetings, back-to-back meetings, and gaps between meetings too short to use.
- **Compared with** the person's 7-day average and the team average. The view highlights anything far from normal.
- The AI agent gets these numbers (it computes none of them) and writes an **"Insights"** paragraph, for example:
  "2h10m in meetings, 4 of them back-to-back after lunch; Slack switches broke the morning into 12-minute pieces;
  the longest focus block was 48 min on ticket #12345."

### 4c. Excel — `apps/api/app/excel/` (openpyxl)
- **Own DSR workbook** (one person or the team, for a day or a date range), with sheets:
  `DSR` (tasks, hours, status, blockers, tomorrow) · `Work Output` (counts plus the full action list:
tickets, emails, docs) · `Meetings` · `Timeline` (every session) ·
  `9-Hour Breakdown` (with a pie chart) · `By App & Site` (with a bar chart) · `Hourly` (heatmap made with
  conditional formatting) · `Team Summary` (manager export only).
- **Fill the company template**: the admin uploads the existing DSR `.xlsx` once and maps fields such as
  `{date}, {name}, {task}, {hours}, {status}, {meetings}, {tickets_responded}, {tickets_resolved},
  {emails_sent}, {remarks}` in one of two ways:
  - **Fixed-cell mode**: a field goes into a set cell (for example B3 = name).
  - **Row-append mode**: from a start row, write one row per task and copy the template row's formatting.
  The mapping is checked with a preview before it is saved. Formulas, styles and other sheets stay unchanged.
- **Output**: a daily file per person, or **append to one master workbook** (one sheet per month, one row
  per task per person). It can be downloaded, attached to the end-of-day email, or saved to a configured
  shared folder.

### 4d. AI on every output: summarise and optimise — `apps/api/app/ai/`
Each output is summarised by the local LLM (mistral-nemo:12b through Ollama), and the summaries roll up
level by level. Code supplies every fact and number. The LLM only writes the text, and a validator checks
what it writes.

| Level | Input (made by code) | What the LLM writes |
|---|---|---|
| **Item** | One Mantis ticket's actions today, with note text · one email thread (subject, recipients and Gmail's `snippet` from metadata, no body) · one doc's edits · one meeting (title, attendees, attendance) · one work block (sessions, window titles) | A one-line summary of what was done on it, e.g. "#12345: diagnosed login timeout, asked client for logs, moved to Feedback" |
| **Section** | All item summaries in a section | Short summaries of Tickets, Email, Docs, Meetings and Focus work |
| **Day (DSR)** | Section summaries + 9-hour analysis + tasks | The DSR text: Tasks, Highlights, Blockers, Tomorrow, Insights |
| **Optimise** | The day analysis, time sinks, meeting load, switches, 7-day trend | 3 to 5 **specific suggestions** for that person, each citing its evidence, e.g. "Email was checked 41 times in 23 short bursts; batching it at 11:00, 14:00 and 17:00 would free about 50 min of focus time" |
| **Team** (manager) | Every person's DSR + analysis | The team's day: progress, overloaded or under-used people, meeting-heavy days, risks, suggestions for the team |
| **Week/Month** | Daily summaries | A weekly or monthly status summary and trend story |

Guards:
- **Number check**: every number in the LLM's text must match a value code computed. If any does not, the
  LLM is asked again; if it still does not match, that sentence is dropped.
- **Reference check**: every ticket ID, document or meeting the LLM mentions must exist in that day's data.
- **JSON schema** for each level. Failed outputs are retried up to 2 times, then the system falls back to a
  summary built by code.
- Suggestions must cite the metric they are based on, and the person can mark each one "useful" or "not useful".
  This feedback is stored and used in later prompts.

Throughput on the 1080 Ti:
- Item summaries are made **during the day** (every 30 min, only for new or changed items).
- They are cached by a hash of their content, so the end-of-day run only does the section, day, optimise and
  team levels.
- One queue at a time, so GPU use stays steady.

Every AI text is used everywhere: in the dashboard, the email, PDF, both kinds of Excel output (summary
columns, and template fields such as `{ai_summary}` and `{ai_suggestions}`) and the master workbook.
Any AI text can be edited by the person before they submit, and the original is kept for audit.

### 5. Web — `apps/web` (Next.js)
- **My Day**: day timeline (Gantt bar by category, with calendar meetings drawn as their own lane), the
  "Where your 9 hours went" breakdown, time sinks, focus score, the AI draft and Insights, confirm or reject
  flagged meetings, edit and reword tasks, remove any item, submit. Shows "what your manager will see".
- **Analysis**: the hourly heatmap, a 7 and 30 day trend for each category, and meeting load, for each
  person and the team.
- **Team (manager)**: one row per person with active, productive and idle hours, DSR status and a link to the
  DSR. Date range view and trends. Charts follow the dataviz skill.
- **Admin**: users and teams, device enrolment codes, category rules and the AI suggestion queue, working hours,
  idle threshold, retention, email schedule, privacy text.
- **Admin** also covers shift and break per team (default 09:00–18:00 with a 60 min break), the Google
  Calendar connection, and the Excel template upload and field mapping.
- **Export**: DSR as PDF (WeasyPrint) and Excel (see 4c), for one person or the team, for a day or a date range.

### 6. Email
At the configured time, a worker job emails each submitted DSR to the manager, plus a team digest.
If a DSR is not submitted by the cutoff, the draft is sent marked "not reviewed" (configurable).
SMTP settings go in this project's own `.local\secrets` and are never committed.

## Privacy and safety (built in)
- No screenshots, no keystroke content and no clipboard. Only app, window title, domain or path, and idle state.
- Private mode, Pause, domain blocklist and incognito are all respected on the device, before any data is sent.
- Each person can see all of their own data. Every manager view of a DSR or timeline is written to `audit_log`.
- A first-run notice explains what is collected. The org's policy text is configurable.

## Build order
1. Repo scaffold, database models and migrations, auth, `/ingest`, plus the sessioniser and rule categoriser with unit tests.
2. Windows agent (SQLite queue, tray, Pause/Private) and an enrolment flow tested against the local API.
3. Browser extension and the link to the agent.
4. Agent DSR pipeline with Ollama, the validator, and the rule-only fallback.
5. 9-hour analysis engine with unit tests.
6. Google Calendar sync and merging meetings with activity.
6b. Collect work output: Mantis actions and time per ticket, Gmail counts, Drive activity, all into
    `work_actions`.
6c. AI layer: item, section, day, optimise and team summaries, with caching and the number and reference checks.
7. Web: My Day, then Analysis, then Team, then Admin.
8. Excel (own workbook, then template filling with field mapping and the master workbook), PDF, email,
   retention job.
9. Seed script with a synthetic day (including meetings) for 3 users, README and docs.

## Verification
- `pytest` unit tests: sessioniser edge cases (midnight crossover, idle splits, overlapping browser and app
  events), rule matching, and validator (missing or duplicate blocks; minutes must match the session total exactly).
- Analysis tests: the 9-hour breakdown always adds up to exactly the shift length; break and overtime are
  handled; meeting overlap is classed as confirmed, possibly skipped or multitasking.
- AI layer: a test set of 3 synthetic days. Insert a wrong number or a ticket ID that does not exist and check
  that the guard rejects it. Check that summaries are reused from the cache. Then do a live mistral-nemo run
  and score the summaries by hand for correctness, and the suggestions for whether they can be acted on.
- Mantis: test with recorded issue, notes and history responses. Each action must be credited to the right
  user, and running the job twice must not create duplicates. Then do a live read-only run for one user for
  one day against the real Mantis and compare the counts with the Mantis UI.
- Gmail and Drive: recorded responses, then check the counts against the user's own Sent folder and Drive
  activity for one day.
- Calendar: test with recorded Google API responses, then a live run against the user's own calendar for one day.
- Excel: fill a sample template in both fixed-cell and row-append modes, reopen it with openpyxl, and check
  that formulas and styles are kept; the master workbook appends without duplicate rows when run twice.
- Integration test: a synthetic day of events goes through `/ingest`, the sessioniser, a mocked Ollama and the
  DSR draft, and the totals are checked.
- Live: run the agent and extension on this PC for an hour, generate the DSR with mistral-nemo, and check the
  timeline against what was actually done. Pause and Private mode must leave gaps with no details.
- Playwright E2E: a resource edits and submits a DSR, the manager sees it, export downloads, and the email is
  sent to a local SMTP sink.

## Later (not in v1)
Jira, other helpdesks and Git as further work-output sources (each would be a new adapter writing to
`work_actions`), installing the extension through Group Policy, macOS agent.
