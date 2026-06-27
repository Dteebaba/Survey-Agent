# Almor LLC — Survey Agent: System Guide

---

## Table of Contents

1. Overview
2. Sign In & Session Management
3. Welcome Screen
4. Home (Landing Page)
5. Operations Hub
6. Autonomous Agent
7. Document Assistant
8. Training
9. AI Tools
10. Admin Console
11. Staff
12. Solicitations
13. Automated Pipeline (GitHub Actions)
14. Role Permissions Summary
15. Data Flow Summary

---

## 1. Overview

The **Survey Agent** is Almor LLC's internal web platform for tracking and managing federal procurement opportunities. It connects to Google Drive (where raw SAM.gov export files are stored), processes them automatically to filter SDVOSB, SDVOSBC, and SBA set-aside solicitations, and writes qualifying records into a master Google Sheet. The platform runs on Render (always-on web app) and uses GitHub Actions for scheduled background pipeline runs every 4 hours.

---

## 2. Sign In & Session Management

**URL:** Your Render deployment link.

**How it works:**
- Users enter their **username** and **password** on the login screen.
- Credentials are validated against the user list stored in a GitHub Gist.
- On successful login a secure browser cookie is set. The session automatically persists — if you close and reopen the tab, you are still logged in.
- Sessions expire after **10 minutes of inactivity**. The cookie is cleared on sign-out.

**Sign Out:**
Available in three places — the sidebar (visible on every page), the Welcome screen, and the Home page. Clicking Sign Out clears the session immediately and returns to the login screen.

---

## 3. Welcome Screen

**Shown once per login session.**

Displays the Almor LLC eagle logo and two entry buttons:

| Button | Destination |
|--------|------------|
| Enter Operations | Opens the Operations Hub |
| View Solicitations | Opens the Solicitations page directly |

A **Sign Out** button is also shown here for users who may have logged in under the wrong account.

---

## 4. Home (Landing Page)

**Shown after dismissing the Welcome screen.**

A hub card layout with two main sections:

| Card | Description |
|------|-------------|
| **Operations** | Access all agent tools, admin console, and settings |
| **Solicitations** | Jump directly to the live solicitations tracker |

- Quick links to the **Google Drive folder** (source files) and **Master Google Sheet** (output) are shown at the top.
- A **Sign Out** button is in the top-right corner.
- Admins see their role displayed; regular users see a streamlined view.

---

## 5. Operations Hub

**Path:** Home → Operations

The central launchpad for all tools. Cards are arranged in two rows.

| Card | Role Required | Description |
|------|--------------|-------------|
| **Autonomous Agent** | Any | Run and monitor the file-scanning pipeline |
| **Document Assistant** | Any | Upload and process a raw SAM.gov export manually |
| **Training** | Any | Video tutorials on SAM.gov and federal bidding |
| **AI Tools** | Any | AI assistants for scoring and summarising opportunities |
| **Admin Console** | Admin only | Manage users and view system logs |
| **Staff** | Admin only | Track user activity, logins, and progress report updates |

---

## 6. Autonomous Agent

**Path:** Operations → Autonomous Agent

Manages the automated pipeline that scans Google Drive for new opportunity files and appends qualifying rows to the master Google Sheet.

### Header Metrics

| Metric | Description |
|--------|-------------|
| Last Run | Date and status icon of the most recent pipeline run |
| Last File Processed | Name of the most recently processed source file |
| Total Files Processed | Cumulative count of source files processed across all runs |
| Total Rows Added | Cumulative count of solicitation rows added to the master sheet |

**Quick Links** (always visible): buttons to open the Google Drive folder and the Master Google Sheet directly.

**Countdown Banner**: A live ticking countdown (hh:mm:ss) to the next scheduled GitHub Actions run, updated every second in the browser.

---

### Tab 1 — ▶ Run / Control

The main control panel.

**Pipeline Lock Banner:** If a run is already in progress (started by any user), a yellow warning appears: *"Pipeline is currently running — started by [user] at [time]. Please wait."* All run/reset buttons are disabled until the run finishes.

**Admin-only buttons:**

| Button | Description |
|--------|-------------|
| ▶ Run Latest Update | Manually triggers the pipeline immediately. Scans Drive for files not yet processed and appends qualifying rows (due 10+ days from today) to the master sheet. Already-processed files are always skipped. |
| 🔄 Reset Seen Files | Clears the pipeline's memory of which files have been processed. The very next run will re-read ALL files in the Drive folder from scratch. Use this after changing the date filter rule or to force a full refresh. |
| Apply Dropdown to Sheet | Re-applies the Progress Report dropdown validation to the master sheet. Use if the dropdown disappears after manual edits in Google Sheets. |
| 📋 View Solicitations | Navigates to the Solicitations page. |

**Regular users** see only the **View Solicitations** button on this tab.

**After a successful run:** A green banner appears — *"Pipeline complete — solicitations have been updated"* — with a full-width **View Updated Solicitations →** button.

---

### Tab 2 — 📋 Run History

A table of every pipeline run (most recent first) showing:

- Run date and time (UTC)
- Who triggered it (Scheduled / Manual)
- Files checked and files processed
- Rows added
- Status (✅ Success / ℹ️ No New Files / ❌ Error)
- Message summary

**Download Run History CSV** button exports the full log.

---

### Tab 3 — 📁 Processed Files

A complete log of every source file that has ever been processed, showing:

- Date and time processed
- Source sheet (filename)
- Number of rows added
- Status (OK / Error)

**Download File Log CSV** button exports the full log.

---

### Tab 4 — ⚠️ Error Log

Shows the 10 most recent pipeline errors with timestamp and error message. A green *"No errors recorded"* message displays when the system is clean.

---

### Tab 5 — ⚙️ Configuration

Explains how the agent works and shows:

- Current filter rule: SDVOSB / SDVOSBC / SBA set-asides, due **10 or more days from today**
- Automatic schedule: every **4 hours** (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
- Quick links to the Drive folder and master sheet

---

## 7. Document Assistant

**Path:** Operations → Document Assistant

Allows any user to upload a raw SAM.gov CSV or Excel export and process it on demand — without waiting for the nightly pipeline.

**Steps:**
1. Upload a CSV or Excel file exported from SAM.gov.
2. The system normalizes columns, classifies set-aside codes (3-tier: direct lookup → description lookup → AI classification), and applies the standard output format.
3. A preview of the processed data is shown.
4. **Download** the result as a clean Excel or CSV file.

This tool does **not** write to the master Google Sheet — it is for one-off analysis and download only.

---

## 8. Training

**Path:** Operations → Training

A library of video tutorials to help the team get the most out of federal procurement tools.

**Current content:**
- *How to use SAM.gov and ChatGPT* (embedded YouTube video)

Additional videos will be added over time. External AI tool links are also provided on this page.

---

## 9. AI Tools

**Path:** Operations → AI Tools

A collection of AI-powered assistants for working with opportunity data:

- **Summarise** a dataset — generate a plain-English summary of opportunities
- **Score / Compare** opportunities based on set-aside type, due date, and agency
- **Create a plan** — AI-generated outline for pursuing a specific opportunity

These tools use the OpenAI API and operate on uploaded files or pasted text.

---

## 10. Admin Console

**Path:** Operations → Admin Console  
**Role required:** Admin only

#### Tab 1 — 👥 User Management

**Add New User form:**

| Field | Description |
|-------|-------------|
| Username | Unique login name for the new user |
| Password | Initial password (stored as a SHA-256 hash) |
| Role | `user` (solicitations only) or `admin` (full access) |

Clicking **Add User** saves the account to the GitHub Gist immediately.

**Current Users list:** All registered accounts shown in expandable cards. Each card shows the username, role, and date created. Admins can change a user's role (except their own account). Accounts are permanent — there is no delete option.

#### Tab 2 — 📊 Activity Logs

Shows a session-scoped log of events that occurred during the current page session (page navigations, data loads, pipeline triggers). This is a lightweight in-session log, separate from the persistent Staff activity log.

---

## 11. Staff

**Path:** Operations → Staff  
**Role required:** Admin only

Tracks what every user has done across the platform, stored persistently in the GitHub Gist.

### Date Range Filter

Select a **From** and **To** date at the top. All tables below update to show only activity within that range.

### Summary Table

One row per registered user, showing:

| Column | Description |
|--------|-------------|
| User | Username |
| Logins | Number of times the user logged in during the date range |
| Active Hours | Estimated active time (login → logout pairs, capped at 2 hours per session; orphaned logins credited 15 min) |
| Bid Submitted | Count of Progress Report updates set to this status |
| Bid InProgress | Count of Progress Report updates set to this status |
| Sub Contractor Inquiry | Count of Progress Report updates set to this status |
| Bid Past Due Date | Count of Progress Report updates set to this status |
| Bid Quote Requested | Count of Progress Report updates set to this status |
| Total Updates | Total Progress Report changes by this user |

### Detailed Activity Log

A filterable table of every individual event:

| Filter | Options |
|--------|---------|
| Filter by user | All / any specific username |
| Filter by action | All / login / logout / progress_update |

Each row shows: timestamp (UTC), username, action, and for `progress_update` events: solicitation number, old status, and new status.

---

## 12. Solicitations

**Path:** Home → View Solicitations (or any navigation button)  
**Role required:** Any authenticated user

The live view of all federal opportunities currently tracked in the master Google Sheet.

### Controls Bar

| Control | Description |
|---------|-------------|
| ← Back to Home | Admins only — returns to the landing page |
| 🔄 Refresh from Sheet | Forces a fresh download from Google Sheets, clearing the 2-minute cache |

### Tab 1 — 📋 All Solicitations

The full master sheet with search, filter, and inline editing.

**Columns displayed:**

| Column | Description |
|--------|-------------|
| Solicitation Number | Unique SAM.gov reference number |
| Title | Opportunity title |
| Agency | Full parent path / agency name |
| Solicitation Date | Date the opportunity was posted |
| Due Date | Response deadline |
| Opportunity Type | Contract type (e.g., Combined Synopsis, Solicitation) |
| Normalized Set Aside | Standardised set-aside code (SDVOSB, TOTAL SMALL BUSINESS SET ASIDE) |
| UiLink | Direct link to the opportunity on SAM.gov |
| Progress Report | Editable status dropdown — changes save automatically to Google Sheets |
| Award Date | Date of award (if applicable) |

**Progress Report options:**
- Bid Submitted
- Bid InProgress
- Sub Contractor Inquiry
- Bid Past Due Date
- Bid Quote Requested

**Auto-save:** Changing a Progress Report value triggers an instant background save to Google Sheets. A *"💾 Saving…"* toast appears, followed by a confirmation once the write is confirmed. All users see the updated value on their next refresh (within 2 minutes).

**Auto-purge:** Rows where the due date is more than 5 days in the past and the Progress Report is empty are automatically removed from the master sheet when the page loads.

**Download buttons:** Export the current filtered view as **Excel (.xlsx)** or **CSV**.

### Tab 2 — 🚨 Urgent (< 10 days)

Shows only solicitations where the due date is **within the next 10 days** (not yet expired). These are the most time-sensitive opportunities requiring immediate attention.

**🔄 Refresh Urgent button:** Triggers a background sync that:
1. Removes any expired rows (past due date) from the Urgent Google Sheet tab
2. Adds any newly-urgent rows from the main sheet
3. Clears the local cache so the updated list is shown on next load

If no urgent solicitations exist, a message confirms *"All due dates are 10+ days away."*

**The Urgent tab in Google Sheets** is also kept in sync automatically after every pipeline run.

---

## 13. Automated Pipeline (GitHub Actions)

The pipeline runs on **GitHub's own servers** — Render does not need to stay awake for it.

**Schedule:** Every 4 hours — 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.

**Manual trigger:** Go to your GitHub repository → Actions → Nightly Opportunity Pipeline → Run workflow.

### What happens on each run:

1. **Sync state** — pull the latest run history and seen-file list from the GitHub Gist.
2. **List Drive files** — scan the Google Drive folder for all CSV and Excel files.
3. **Skip seen files** — any file already processed is skipped; only new files are read.
4. **Normalize** — standardise column names, classify set-aside codes (3-tier: code lookup → description lookup → AI/LLM classification).
5. **Filter** — keep only SDVOSB, SDVOSBC, or SBA set-aside solicitations where the due date is **10 or more days from today**.
6. **Deduplicate** — check the master sheet; skip any solicitation number or UiLink already present.
7. **Append** — write qualifying rows to the *Opportunities* tab of the master Google Sheet.
8. **Cleanup** — delete rows from the master sheet where the due date is more than 5 days past and Progress Report is empty.
9. **Refresh Urgent tab** — update the *Urgent* sheet tab: remove expired rows, add newly-urgent rows (due within 10 days).
10. **Save state** — write updated run log and seen-file list back to the GitHub Gist so the app dashboard reflects the latest run.

**Required GitHub Secrets:**

| Secret | Purpose |
|--------|---------|
| GH_TOKEN | GitHub Personal Access Token (gist scope) for reading/writing the Gist |
| GIST_ID | ID of the Gist used to store run state and user data |
| GOOGLE_SERVICE_ACCOUNT_JSON | Full JSON key for the Google service account |
| GOOGLE_DRIVE_FOLDER_ID | ID of the Drive folder containing source files |
| GOOGLE_SHEETS_ID | ID of the master output spreadsheet |
| OPENAI_API_KEY | OpenAI API key for LLM-based set-aside classification |

---

## 14. Role Permissions Summary

| Feature | Regular User | Admin |
|---------|-------------|-------|
| Sign in / Sign out | ✅ | ✅ |
| View Solicitations (All tab) | ✅ | ✅ |
| View Urgent tab | ✅ | ✅ |
| Update Progress Report | ✅ | ✅ |
| Download solicitations (CSV/Excel) | ✅ | ✅ |
| Refresh from Sheet | ✅ | ✅ |
| View Operations Hub | ❌ | ✅ |
| Run pipeline manually | ❌ | ✅ |
| Reset Seen Files | ❌ | ✅ |
| Apply Dropdown to Sheet | ❌ | ✅ |
| View Run History / File Log / Errors | ❌ | ✅ |
| Admin Console (manage users) | ❌ | ✅ |
| Staff (activity tracking) | ❌ | ✅ |
| Document Assistant | ❌ | ✅ |
| AI Tools | ❌ | ✅ |
| Training | ❌ | ✅ |

---

## 15. Data Flow Summary

```
SAM.gov (export) → Google Drive folder
                        ↓
              GitHub Actions (every 4 hours)
              or Manual Run in app
                        ↓
              Normalize + Filter + Deduplicate
                        ↓
         ┌──────────────────────────────┐
         │  Master Google Sheet         │
         │  Tab: Opportunities          │  ← all qualifying rows (10+ days)
         │  Tab: Urgent                 │  ← due within 10 days (auto-synced)
         └──────────────────────────────┘
                        ↓
              Streamlit App on Render
              - View / filter / search
              - Update Progress Report (writes back to sheet live)
              - Staff activity logged to GitHub Gist
```

---

*Document generated by Claude Code for Almor LLC internal use.*  
*Last updated: June 2026*
