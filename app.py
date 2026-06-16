import datetime
import json
import hashlib
from pathlib import Path
import streamlit as st

# Initialize default admin on first run
from init_admin import create_default_admin
create_default_admin()

from auth import check_access
from data_engine import (
    load_dataset,
    build_full_eda,
    normalize_set_aside_column,
    normalize_opportunity_type_column,
    build_final_output_table,
    to_excel_bytes,
    to_csv_bytes,
    apply_filters,
)
from llm_agent import summarize_dataset, create_llm_plan


# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(
    page_title="Survey Agent – Almor LLC",
    page_icon="📊",
    layout="wide",
)

# Load CSS
css_path = Path("assets/style.css")
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# -------------------------------------------------
# AUTH + SESSION STATE
# -------------------------------------------------
check_access()

# First run after login: sync state from Gist then show welcome splash
if "app_initialized" not in st.session_state:
    st.session_state["app_initialized"] = True
    st.session_state["page"] = "welcome"
    st.session_state["results_ready"] = False
    st.session_state["activity_log"] = []
    # Pull latest agent state from GitHub Gist (non-blocking — errors are silent)
    try:
        from agent_state import sync_from_gist
        sync_from_gist()
    except Exception:
        pass
else:
    st.session_state.setdefault("page", "landing")
    st.session_state.setdefault("results_ready", False)
    st.session_state.setdefault("activity_log", [])


def goto(page: str):
    st.session_state.page = page
    st.rerun()


def log_event(action: str, status: str, message: str = "", extra: dict | None = None):
    st.session_state.activity_log.append({
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "role": st.session_state.get("role", "unknown"),
        "action": action,
        "status": status,
        "message": message,
        "extra": extra or {},
    })


# -------------------------------------------------
# USER MANAGEMENT FUNCTIONS (ADMIN ONLY)
# -------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def load_users():
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        st.error(f"Error loading users: {e}")
        return []


def save_users(users):
    try:
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=4)
        from auth import save_users_to_gist
        save_users_to_gist(users)
        return True
    except Exception as e:
        st.error(f"Error saving users: {e}")
        return False


def add_user(username: str, password: str, role: str = "user"):
    if st.session_state.get("role") != "admin":
        return False, "Access denied. Only admins can add users."
    if len(username.strip()) < 3:
        return False, "Username must be at least 3 characters long."
    if len(password) < 6:
        return False, "Password must be at least 6 characters long."
    users = load_users()
    if any(user['username'].lower() == username.lower() for user in users):
        return False, "Username already exists."
    hashed_pw = hash_password(password)
    new_user = {
        'username': username.strip(),
        'password': hashed_pw,
        'role': role,
        'created_at': datetime.datetime.now().isoformat(),
        'created_by': st.session_state.get("username", "unknown")
    }
    users.append(new_user)
    if save_users(users):
        log_event("add_user", "success", f"Added user: {username}")
        return True, f"User '{username}' added successfully!"
    else:
        return False, "Failed to save user data."


def delete_user(username: str):
    if st.session_state.get("role") != "admin":
        return False, "Access denied. Only admins can delete users."
    users = load_users()
    if username == st.session_state.get("username"):
        return False, "You cannot delete your own account."
    original_count = len(users)
    users = [user for user in users if user['username'] != username]
    if len(users) == original_count:
        return False, f"User '{username}' not found."
    if save_users(users):
        log_event("delete_user", "success", f"Deleted user: {username}")
        return True, f"User '{username}' deleted successfully!"
    else:
        return False, "Failed to save user data."


def update_user_role(username: str, new_role: str):
    if st.session_state.get("role") != "admin":
        return False, "Access denied. Only admins can update user roles."
    users = load_users()
    for user in users:
        if user['username'] == username:
            old_role = user['role']
            user['role'] = new_role
            user['updated_at'] = datetime.datetime.now().isoformat()
            user['updated_by'] = st.session_state.get("username", "unknown")
            if save_users(users):
                log_event("update_user_role", "success",
                         f"Updated {username} role from {old_role} to {new_role}")
                return True, f"User '{username}' role updated to '{new_role}'!"
            else:
                return False, "Failed to save user data."
    return False, f"User '{username}' not found."


# -------------------------------------------------
# EXTERNAL TOOLS UI
# -------------------------------------------------
def render_external_tools():
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem;">
            External AI & Research Tools
        </div>
        <p style="color:#374151; font-size:0.9rem; margin-bottom:0.8rem;">
            Click a tool below to continue your analysis or proposal workflow.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        .ext-btn {
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 0.5rem;
            padding: 0.45rem 0.9rem;
            border-radius: 999px;
            background: #F3F4F6;
            color: #111827 !important;
            border: 1px solid #D1D5DB;
            font-size: 0.85rem;
            text-decoration: none;
            font-weight: 500;
        }
        .ext-btn:hover { background: #E5E7EB; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <a class="ext-btn" href="https://chatgpt.com/g/g-67df3383b37c81919e4fd38381e15a3b-sources-sought-analyzer" target="_blank">Sources Sought Analyzer</a>
        <a class="ext-btn" href="https://chatgpt.com/g/g-68c8e4688328819182428ed714ade74a-breakdown-statement-of-works" target="_blank">Breakdown Statement of Work</a>
        <a class="ext-btn" href="https://chatgpt.com" target="_blank">ChatGPT</a>
        <a class="ext-btn" href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer" target="_blank">Sam Excel Solicitation Analyzer</a>
        <a class="ext-btn" href="https://www.perplexity.ai/" target="_blank">Perplexity AI</a>
        <a class="ext-btn" href="https://www.google.com" target="_blank">Google Search</a>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# WELCOME / SPLASH PAGE
# Shown once per session immediately after login.
# Almor LLC logo and SBA certification swivel in.
# -------------------------------------------------

# SVG representations of the logos (embedded inline — no external files needed)
_ALMOR_SVG = """
<svg viewBox="0 0 270 88" xmlns="http://www.w3.org/2000/svg"
     style="width:270px;height:88px;display:block">
  <!-- Hexagon (flat-top: pointy left/right) -->
  <polygon points="44,6 80,6 98,44 80,82 44,82 26,44"
           fill="#1E4D0F" stroke="#163809" stroke-width="1.5"/>
  <!-- White A -->
  <text x="62" y="66"
        font-family="Georgia,'Times New Roman',serif"
        font-size="54" font-weight="bold"
        fill="white" text-anchor="middle">A</text>
  <!-- Almor -->
  <text x="158" y="47"
        font-family="'Segoe UI','Helvetica Neue',Arial,sans-serif"
        font-size="28" font-weight="800" fill="#1E4D0F"
        letter-spacing="-0.4">Almor</text>
  <!-- LLC -->
  <text x="164" y="67"
        font-family="'Segoe UI','Helvetica Neue',Arial,sans-serif"
        font-size="15" fill="#1E4D0F" letter-spacing="3">LLC</text>
</svg>
"""

_SBA_SVG = """
<svg viewBox="0 0 180 222" xmlns="http://www.w3.org/2000/svg"
     style="width:180px;height:222px;display:block">
  <!-- White background -->
  <rect x="0" y="0" width="180" height="222" fill="white"/>
  <!-- Outer border -->
  <rect x="2" y="2" width="176" height="218" fill="none"
        stroke="#1B2C8A" stroke-width="3.5"/>
  <!-- Inner border -->
  <rect x="8" y="8" width="164" height="206" fill="none"
        stroke="#1B2C8A" stroke-width="1.5"/>
  <!-- Top-left corner bracket -->
  <rect x="18" y="18" width="30" height="4" fill="#1B2C8A"/>
  <rect x="18" y="18" width="4"  height="30" fill="#1B2C8A"/>
  <!-- Top-right corner bracket -->
  <rect x="132" y="18" width="30" height="4" fill="#1B2C8A"/>
  <rect x="158" y="18" width="4"  height="30" fill="#1B2C8A"/>
  <!-- SBA text -->
  <text x="90" y="86"
        font-family="'Arial Black',Arial,sans-serif"
        font-size="54" font-weight="900" fill="#1B2C8A"
        text-anchor="middle" letter-spacing="-2">SBA</text>
  <!-- Red horizontal bar (SBA logo accent) -->
  <rect x="22" y="94" width="136" height="6" fill="#CC1111"/>
  <!-- U.S. Small Business Administration -->
  <text x="90" y="116"
        font-family="Arial,sans-serif" font-size="10.5"
        fill="#1B2C8A" text-anchor="middle" font-weight="600">U.S. Small Business</text>
  <text x="90" y="131"
        font-family="Arial,sans-serif" font-size="10.5"
        fill="#1B2C8A" text-anchor="middle" font-weight="600">Administration</text>
  <!-- Navy bottom banner -->
  <rect x="2" y="148" width="176" height="72" fill="#1B2C8A"/>
  <!-- White certification text -->
  <text x="90" y="170"
        font-family="'Arial Black',Arial,sans-serif"
        font-size="11.5" font-weight="900" fill="white"
        text-anchor="middle" letter-spacing="0.3">SERVICE-DISABLED</text>
  <text x="90" y="188"
        font-family="'Arial Black',Arial,sans-serif"
        font-size="11.5" font-weight="900" fill="white"
        text-anchor="middle" letter-spacing="0.3">VETERAN-OWNED</text>
  <text x="90" y="207"
        font-family="'Arial Black',Arial,sans-serif"
        font-size="11.5" font-weight="900" fill="white"
        text-anchor="middle" letter-spacing="0.3">CERTIFIED</text>
</svg>
"""


def show_welcome():
    st.markdown(
        f"""
        <div class="welcome-outer">
            <div class="welcome-logos-row">
                <div class="swivel-left logo-drop-shadow">
                    {_ALMOR_SVG}
                </div>
                <div class="welcome-divider swivel-left" style="animation-delay:0.2s"></div>
                <div class="swivel-right logo-drop-shadow">
                    {_SBA_SVG}
                </div>
            </div>
            <div class="welcome-brand fade-up">Survey Agent</div>
            <div class="welcome-tagline fade-up" style="animation-delay:1.15s">
                Almor LLC · Federal Opportunity Intelligence Platform
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    _, center, _ = st.columns([3, 2, 3])
    with center:
        if st.button("Enter Workspace", use_container_width=True, type="primary"):
            goto("landing")


# -------------------------------------------------
# LANDING PAGE  (Operations | Solicitations)
# -------------------------------------------------
def show_landing():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    # Compact header with Almor branding
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:1.2rem;margin-bottom:2rem;">
            {_ALMOR_SVG}
            <div>
                <div style="font-size:0.8rem;color:#6B7280;letter-spacing:0.05em;text-transform:uppercase;">
                    Federal Opportunity Intelligence
                </div>
                <div style="font-size:1.05rem;color:#374151;font-weight:600;">
                    Welcome, {st.session_state.get('username', 'User')}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="landing-tile-grid">
            <div class="landing-tile landing-tile-ops">
                <span class="landing-tile-icon">⚙️</span>
                <div class="landing-tile-title">Operations</div>
                <div class="landing-tile-desc">
                    Document assistant, AI analysis tools, autonomous agent,
                    and system management — all in one place.
                </div>
            </div>
            <div class="landing-tile landing-tile-sol">
                <span class="landing-tile-icon">📋</span>
                <div class="landing-tile-title">Solicitations</div>
                <div class="landing-tile-desc">
                    Live view of the master opportunity sheet.
                    Browse all solicitations and update bid status directly on the platform.
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='landing-btn-ops'>", unsafe_allow_html=True)
        if st.button("Open Operations →", use_container_width=True):
            goto("operations")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='landing-btn-sol'>", unsafe_allow_html=True)
        if st.button("View Solicitations →", use_container_width=True):
            goto("solicitations")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# TRAINING PAGE
# -------------------------------------------------
def show_training():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Training Videos</div>
            <div class='app-subtitle'>Learn how to use SAM.gov, ChatGPT, and federal opportunity tools.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("← Back to Operations"):
        goto("operations")
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### How to use Sam.gov and ChatGPT", unsafe_allow_html=True)
    st.video("https://www.youtube.com/watch?v=Nyvwo7es3wo")
    st.markdown(
        "<p style='color:#6B7280; font-size:0.9rem;'>More training videos will be added soon…</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    render_external_tools()
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# OPERATIONS PAGE  (formerly "Home")
# -------------------------------------------------
def show_operations():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Operations</div>
            <div class='app-subtitle'>AI-powered tools for managing federal opportunity spreadsheets.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Home"):
        goto("landing")

    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    st.markdown(
        """<div class='feature-card'><div class='feature-title'>Document Assistant</div>
        <div class='feature-desc'>Upload data, normalize it, and apply AI filters.</div>""",
        unsafe_allow_html=True,
    )
    if st.button("Open Document Assistant"):
        goto("survey")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """<div class='feature-card'><div class='feature-title'>Training</div>
        <div class='feature-desc'>Watch tutorials and learn how to use SAM.gov & AI tools.</div>""",
        unsafe_allow_html=True,
    )
    if st.button("View Training"):
        goto("training")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """<div class='feature-card'><div class='feature-title'>AI Tools</div>
        <div class='feature-desc'>Use specialized AI tools to analyze federal opportunities.</div>""",
        unsafe_allow_html=True,
    )
    if st.button("Open Tools"):
        goto("tools")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """<div class='feature-card'><div class='feature-title'>Autonomous Agent</div>
        <div class='feature-desc'>Auto-scan Drive for the latest file, filter SDVOSB/SBA opps due in 14 days, append to master sheet.</div>""",
        unsafe_allow_html=True,
    )
    if st.button("Open Autonomous Agent"):
        goto("autonomous")
    st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.get("role") == "admin":
        st.markdown(
            """<div class='feature-card'><div class='feature-title'>Admin Console</div>
            <div class='feature-desc'>Manage users and view system activity.</div>""",
            unsafe_allow_html=True,
        )
        if st.button("Open Admin Console"):
            goto("admin")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# SOLICITATIONS PAGE
# Live view of the master Google Sheet with
# editable Progress Report status column.
# -------------------------------------------------
_PROGRESS_OPTIONS = [
    "",
    "Bid Submitted",
    "Bid InProgress",
    "Sub Contractor Inquiry",
    "Bid Past Due Date",
    "Bid Quote Requested",
]


def show_solicitations():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Solicitations</div>
            <div class='app-subtitle'>
                Live view of tracked federal opportunities.
                Update bid status directly — changes are saved back to the master sheet.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_back, col_refresh, col_spacer = st.columns([2, 2, 6])
    with col_back:
        if st.button("← Back to Home"):
            goto("landing")
    with col_refresh:
        if st.button("Refresh Data"):
            st.session_state.pop("sol_data", None)
            st.session_state.pop("sol_original_progress", None)
            st.rerun()

    # ── Load data ────────────────────────────────
    if "sol_data" not in st.session_state:
        with st.spinner("Loading solicitations from master sheet…"):
            try:
                from google_connector import read_master_sheet
                df = read_master_sheet()
                st.session_state["sol_data"] = df
                if "Progress Report" in df.columns:
                    st.session_state["sol_original_progress"] = (
                        df["Progress Report"].copy().reset_index(drop=True)
                    )
                else:
                    st.session_state["sol_original_progress"] = None
            except Exception as e:
                st.error(f"Failed to load sheet data: {e}")
                st.markdown("</div>", unsafe_allow_html=True)
                return

    df = st.session_state["sol_data"]

    if df.empty:
        st.info("No solicitations found in the master sheet yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── Stats bar ─────────────────────────────────
    total = len(df)
    with_status = int((df.get("Progress Report", "") != "").sum()) if "Progress Report" in df.columns else 0
    st.markdown(
        f"""
        <div style="display:flex;gap:1.5rem;margin-bottom:1rem;flex-wrap:wrap;">
            <div class="sol-stat-card">📋 {total} Solicitations</div>
            <div class="sol-stat-card">🏷️ {with_status} With Status</div>
            <div class="sol-stat-card">⏳ {total - with_status} Pending Review</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Data editor ───────────────────────────────
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("**Edit** the _Progress Report_ column below, then click **Save Status Changes**.",
                unsafe_allow_html=True)

    col_cfg = {}
    if "Progress Report" in df.columns:
        col_cfg["Progress Report"] = st.column_config.SelectboxColumn(
            "Progress Report",
            options=_PROGRESS_OPTIONS,
            required=False,
            width="medium",
        )
    if "UiLink" in df.columns:
        col_cfg["UiLink"] = st.column_config.LinkColumn(
            "Link", display_text="View on SAM.gov", width="small"
        )
    if "Due Date" in df.columns:
        col_cfg["Due Date"] = st.column_config.DateColumn("Due Date", width="small")
    if "Solicitation Date" in df.columns:
        col_cfg["Solicitation Date"] = st.column_config.DateColumn("Solicitation Date", width="small")

    editable = ["Progress Report"] if "Progress Report" in df.columns else []
    disabled = [c for c in df.columns if c not in editable]

    edited_df = st.data_editor(
        df,
        column_config=col_cfg,
        disabled=disabled,
        use_container_width=True,
        num_rows="fixed",
        key="sol_editor",
        height=520,
    )

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Save button ───────────────────────────────
    _, save_col, _ = st.columns([4, 3, 4])
    with save_col:
        save_clicked = st.button("💾  Save Status Changes", type="primary", use_container_width=True)

    if save_clicked:
        original_prog = st.session_state.get("sol_original_progress")
        updates = {}

        if original_prog is not None and "Progress Report" in edited_df.columns:
            for i, new_val in enumerate(edited_df["Progress Report"]):
                old_val = original_prog.iloc[i] if i < len(original_prog) else ""
                new_val_str = str(new_val or "")
                old_val_str = str(old_val or "")
                if new_val_str != old_val_str:
                    updates[i + 2] = new_val_str  # sheet rows: 1=header, data starts at 2

        if updates:
            with st.spinner(f"Saving {len(updates)} change(s) to master sheet…"):
                try:
                    from google_connector import update_progress_reports
                    count = update_progress_reports(updates)
                    # Update cached original so next save compares correctly
                    st.session_state["sol_original_progress"] = (
                        edited_df["Progress Report"].copy().reset_index(drop=True)
                    )
                    st.session_state["sol_data"] = edited_df.copy()
                    log_event("update_progress", "success", f"{count} rows updated")
                    st.success(f"✅ {count} status update(s) saved to master sheet.")
                except Exception as e:
                    log_event("update_progress", "error", str(e))
                    st.error(f"Save failed: {e}")
        else:
            st.info("No changes detected.")

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# AUTONOMOUS AGENT PAGE  — comprehensive dashboard
# -------------------------------------------------
def show_autonomous_agent():
    import os
    import pandas as pd
    from datetime import datetime, timedelta
    from agent_state import get_summary, reset_state, record_run

    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Autonomous Agent</div>
            <div class='app-subtitle'>
                Checks Google Drive for new opportunity files, filters SDVOSB / SDVOSBC / SBA
                solicitations due within 14&nbsp;days, and appends them to the master sheet.
                Runs automatically every night at <strong>10 PM ET</strong>.
                Every run — scheduled or manual — is saved to disk.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Operations"):
        goto("operations")

    # ── Scheduler health ──────────────────────────────────────
    st.info(
        "🤖 **Nightly runs are handled by GitHub Actions** — fires at **10 PM ET** "
        "every night on GitHub's own servers. No server needs to stay awake. "
        "The manual run button below works anytime, from anywhere."
    )

    # ── Headline metrics ──────────────────────────────────────
    s = get_summary()

    def _fmt(val):
        return str(val) if val and str(val) not in ("None", "—") else "—"

    last_entry = s.get("last_run_entry")
    if last_entry:
        last_status_icon = {"success": "✅", "error": "❌", "no_new_files": "ℹ️"}.get(
            last_entry.get("status", ""), "—"
        )
        last_run_label = (
            f"{last_status_icon} "
            + datetime.fromisoformat(last_entry["timestamp"]).strftime("%Y-%m-%d %H:%M UTC")
            + f"  ({last_entry.get('triggered_by', '?')})"
        )
    else:
        last_run_label = "Never"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last Run",              last_run_label)
    c2.metric("Last File Processed",   _fmt(s["last_file_processed"]))
    c3.metric("Total Files Processed", s["total_files_processed"])
    c4.metric("Total Rows Added",      s["total_rows_added"])

    # ── Tabbed detail sections ────────────────────────────────
    tab_run, tab_history, tab_files, tab_errors, tab_cfg = st.tabs([
        "▶ Run / Control",
        "📋 Run History",
        "📁 Processed Files",
        "⚠️ Error Log",
        "⚙️ Configuration",
    ])

    # ── Tab 1: Run / Control ──────────────────────────────────
    with tab_run:
        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown(
            """
            **How it works:**
            - **GitHub Actions fires automatically at 10&nbsp;PM ET** every night
              using GitHub's own servers — no server of yours needs to stay awake.
            - If you click **Run Latest Update**, the agent checks Drive for any files
              it hasn't processed yet. Already-processed files are always skipped —
              so a manual run never double-counts data.
            - Every run saves its result to disk, so the dashboard is always up-to-date
              even after a server restart.
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        col_btn, col_reset, col_dv = st.columns([3, 2, 2])
        with col_btn:
            run_now = st.button("▶ Run Latest Update", type="primary", use_container_width=True)
        with col_reset:
            reset_btn = st.button(
                "🔄 Reset Seen Files", type="secondary", use_container_width=True,
                help="Clears the processed-file memory. The next run will re-process ALL files."
            )
        with col_dv:
            apply_dv = st.button(
                "Apply Dropdown to Sheet", type="secondary", use_container_width=True,
                help="Re-applies the Progress Report dropdown validation to the master sheet."
            )

        if reset_btn:
            reset_state()
            st.success("✅ Memory cleared. The next run will process all files from scratch.")

        if apply_dv:
            with st.spinner("Applying dropdown…"):
                try:
                    from google_connector import apply_progress_dropdown
                    apply_progress_dropdown()
                    st.success("✅ Progress Report dropdown applied to master sheet.")
                except Exception as e:
                    st.error(f"Failed: {e}")

        if run_now:
            from autonomous_agent import run_pipeline

            progress_box = st.empty()
            result_box   = st.empty()

            def _cb(msg):
                progress_box.info(f"⏳ {msg}")

            with st.spinner("Running pipeline…"):
                try:
                    summary = run_pipeline(progress_callback=_cb)
                    progress_box.empty()

                    # Persist the run to disk
                    record_run("manual", summary)

                    if summary["errors"]:
                        result_box.error(
                            "Pipeline encountered errors:\n" + "\n".join(summary["errors"])
                        )
                    elif summary["files_processed"] == 0:
                        result_box.info(f"ℹ️ {summary.get('message', 'No new files to process.')}")
                    else:
                        names = ", ".join(
                            f["name"] for f in summary.get("processed_files", [])
                        )
                        rows  = summary["total_rows_added"]
                        result_box.success(
                            f"✅ **{rows} rows** appended from: {names}"
                        )

                    log_event(
                        "autonomous_pipeline",
                        "success" if not summary["errors"] else "error",
                        f"files={summary['files_checked']}, rows={summary['total_rows_added']}",
                    )

                except Exception as e:
                    progress_box.empty()
                    result_box.error(f"Pipeline failed: {e}")

        # Last run detail card
        if last_entry:
            st.markdown("<div class='app-card' style='margin-top:1.25rem'>", unsafe_allow_html=True)
            st.markdown("#### Last Run Report", unsafe_allow_html=True)

            ts = datetime.fromisoformat(last_entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S UTC")
            trig = last_entry.get("triggered_by", "?").capitalize()
            status_label = {
                "success":       "✅ Success",
                "error":         "❌ Error",
                "no_new_files":  "ℹ️ No New Files",
            }.get(last_entry.get("status", ""), "—")

            cols = st.columns(4)
            cols[0].metric("Time",            ts)
            cols[1].metric("Triggered By",    trig)
            cols[2].metric("Files Processed", last_entry.get("files_processed", 0))
            cols[3].metric("Rows Added",      last_entry.get("rows_added", 0))

            st.markdown(f"**Status:** {status_label}")
            st.markdown(f"**Message:** {last_entry.get('message', '—')}")

            pf = last_entry.get("processed_files", [])
            if pf:
                st.markdown("**Files in this run:** " + ", ".join(pf))

            errs = last_entry.get("errors", [])
            if errs:
                st.markdown("**Errors:**")
                for err in errs:
                    st.error(err)

            st.markdown("</div>", unsafe_allow_html=True)

    # ── Tab 2: Run History ────────────────────────────────────
    with tab_history:
        run_log = s.get("run_log", [])

        if not run_log:
            st.info("No run history yet. The log will fill up after the first pipeline run.")
        else:
            rows_for_table = []
            for entry in run_log:                 # already most-recent-first
                ts = entry.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    ts_fmt = ts

                status_icon = {
                    "success":      "✅ Success",
                    "error":        "❌ Error",
                    "no_new_files": "ℹ️ No New Files",
                }.get(entry.get("status", ""), "—")

                rows_for_table.append({
                    "Timestamp (UTC)":  ts_fmt,
                    "Triggered By":     entry.get("triggered_by", "?").capitalize(),
                    "Status":           status_icon,
                    "Files Checked":    entry.get("files_checked", 0),
                    "Files Processed":  entry.get("files_processed", 0),
                    "Rows Added":       entry.get("rows_added", 0),
                    "Message":          entry.get("message", "")[:120],
                })

            df_log = pd.DataFrame(rows_for_table)
            st.markdown(f"**{len(df_log)} run(s) recorded** (most recent first)")
            st.dataframe(df_log, use_container_width=True, height=480)

            col_dl, _ = st.columns([2, 5])
            with col_dl:
                csv_bytes = df_log.to_csv(index=False).encode()
                st.download_button(
                    "Download Run Log CSV",
                    csv_bytes,
                    "run_history.csv",
                    mime="text/csv",
                )

    # ── Tab 3: Processed Files ────────────────────────────────
    with tab_files:
        pf_list = s.get("processed_files", [])

        if not pf_list:
            st.info("No files processed yet.")
        else:
            rows_pf = []
            for pf in reversed(pf_list):          # most recent first
                ts = pf.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    ts_fmt = ts
                rows_pf.append({
                    "Timestamp (UTC)": ts_fmt,
                    "File Name":       pf.get("name", ""),
                    "Rows Added":      pf.get("rows_added", 0),
                    "Status":          pf.get("status", "ok").upper(),
                })

            df_pf = pd.DataFrame(rows_pf)
            st.markdown(
                f"**{len(df_pf)} files** in the processed-file log "
                f"(total rows ever added: **{s['total_rows_added']}**)"
            )
            st.dataframe(df_pf, use_container_width=True, height=480)

            col_dl2, _ = st.columns([2, 5])
            with col_dl2:
                csv2 = df_pf.to_csv(index=False).encode()
                st.download_button(
                    "Download File Log CSV",
                    csv2,
                    "processed_files.csv",
                    mime="text/csv",
                )

    # ── Tab 4: Error Log ──────────────────────────────────────
    with tab_errors:
        all_errors = s.get("recent_errors", [])

        if not all_errors:
            st.success("No errors recorded.")
        else:
            for err in reversed(all_errors):
                ts = err.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    ts_fmt = ts
                st.error(f"[{ts_fmt}]  {err.get('message', '')}")

    # ── Tab 5: Configuration ──────────────────────────────────
    with tab_cfg:
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1bSGpFbEW09jAq6pdn1i_WO8RUAa3DPUJ")
        sheet_id  = os.getenv("GOOGLE_SHEETS_ID",       "151jig9_3v-__dHfk7TksitJYONDMOLQV")

        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### How automatic scheduling works")
        st.markdown(
            """
            Nightly runs are powered by **GitHub Actions** — a free service built into
            every GitHub repository. A workflow file (`.github/workflows/nightly_pipeline.yml`)
            tells GitHub to run `python pipeline_job.py` at **10:00 PM ET** every night
            using GitHub's own cloud servers. Your laptop, Streamlit Cloud, and this web app
            do not need to be running.

            | Component | Role |
            |---|---|
            | **GitHub Actions** | Fires the pipeline at 10 PM ET — always on, always free |
            | **Streamlit Community Cloud** | Hosts this web UI — free, deploys from GitHub |
            | **GitHub Gist** | Stores run history and processed-file list across all platforms |
            | **Google Drive** | Source of daily opportunity CSV files |
            | **Google Sheets** | Master output sheet — rows appended here |

            **De-duplication is automatic.** Every processed Drive file ID is stored in the
            Gist-backed state. Whether the trigger is GitHub Actions or the manual button,
            files already processed are always skipped — no double-counting ever.
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### Links")
        st.markdown(
            f"- **Drive Folder:** [Open in Drive](https://drive.google.com/drive/folders/{folder_id})\n"
            f"- **Output Sheet:** [Open in Sheets](https://docs.google.com/spreadsheets/d/{sheet_id})\n"
            f"- **Filter:** SDVOSB / SDVOSBC / SBA set-asides, due within the next **14 days**\n"
            f"- **Auto Schedule:** Daily at **10 PM ET**"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# TOOLS PAGE
# -------------------------------------------------
def show_tools():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>External Tools</div>
            <div class='app-subtitle'>Use these tools to support your analysis workflows.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("← Back to Operations"):
        goto("operations")
    render_external_tools()
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# DOCUMENT ASSISTANT
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>Upload, normalize, filter, and export federal opportunity datasets.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("← Back to Operations"):
        goto("operations")

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded_file:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dataset_name = uploaded_file.name
    try:
        df = load_dataset(uploaded_file)
    except Exception as e:
        st.error(f"Could not load file: {e}")
        render_external_tools()
        return

    st.markdown(
        f"<p class='data-meta'>Loaded <b>{dataset_name}</b> — Rows: {len(df)} | Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )
    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    eda = build_full_eda(df)

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Dataset Understanding (Click to Generate)", unsafe_allow_html=True)
    if st.button("Generate Dataset Summary"):
        with st.spinner("AI analyzing your dataset..."):
            try:
                summary = summarize_dataset(eda)
            except Exception as e:
                summary = f"(AI failed: {e})"
        st.write(summary)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What do you want to extract or filter?")
    user_request = st.text_area(
        "Instruction",
        placeholder="Example: Show SDVOSB solicitations due in the next 14 days",
        height=120,
    )
    run_btn = st.button("Run Analysis")
    st.markdown("</div>", unsafe_allow_html=True)

    if not run_btn:
        render_external_tools()
        return

    if not user_request.strip():
        st.warning("Please provide an instruction.")
        render_external_tools()
        return

    with st.status("Processing your request...", expanded=True) as status:
        status.update(label="Interpreting your instruction...", state="running")
        try:
            plan = create_llm_plan(eda, user_request)
        except Exception as e:
            st.error(f"AI plan failed: {e}")
            return

        columns     = plan.get("columns", {})
        sa_patterns = plan.get("set_aside_patterns", {})
        opp_patterns= plan.get("opportunity_type_patterns", {})
        filters     = plan.get("filters", [])

        status.update(label="Normalizing...", state="running")
        df2 = df.copy()
        df2 = normalize_set_aside_column(df2, columns.get("set_aside_column") or "TypeOfSetAsideDescription", sa_patterns)
        df2 = normalize_opportunity_type_column(df2, columns.get("opportunity_type_column") or "Type", opp_patterns)

        status.update(label="Building final output...", state="running")
        try:
            final_df = build_final_output_table(df2, columns)
            final_df = apply_filters(final_df, filters)
        except Exception as e:
            st.error(f"Error building output: {e}")
            return

        status.update(label="Complete", state="complete")

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Filtered Results", unsafe_allow_html=True)
    st.write(f"Rows returned: **{len(final_df)}**")

    if len(final_df) > 0:
        st.dataframe(final_df.head(50))
        excel_bytes = to_excel_bytes(final_df)
        csv_bytes   = to_csv_bytes(final_df)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("Download Excel", excel_bytes, "Filtered_Results.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with c2:
            st.download_button("Download CSV", csv_bytes, "Filtered_Results.csv", mime="text/csv")
    else:
        st.warning("No rows matched your filter criteria.")

    st.markdown("</div>", unsafe_allow_html=True)
    render_external_tools()
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ADMIN PAGE
# -------------------------------------------------
def show_admin():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    if st.session_state.get("role") != "admin":
        st.error("Access denied. Only administrators can access this page.")
        if st.button("← Back to Operations"):
            goto("operations")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Admin Console</div>
            <div class='app-subtitle'>Manage users and view system activity.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("← Back to Operations"):
        goto("operations")

    tab1, tab2 = st.tabs(["👥 User Management", "📊 Activity Logs"])

    with tab1:
        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### Add New User")
        with st.form("add_user_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_username = st.text_input("Username", placeholder="Enter username")
                new_password = st.text_input("Password", type="password", placeholder="Enter password")
            with col2:
                new_role     = st.selectbox("Role", ["user", "admin"], index=0)
                st.write("")
                submit_add   = st.form_submit_button("Add User", use_container_width=True)
            if submit_add:
                if new_username and new_password:
                    success, message = add_user(new_username, new_password, new_role)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                else:
                    st.warning("Please fill in both username and password.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### Current Users")
        users = load_users()
        if not users:
            st.info("No users found. Add the first user above.")
        else:
            for i, user in enumerate(users):
                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                with col1:
                    st.write(f"**{user['username']}**")
                with col2:
                    current_role = user['role']
                    new_role = st.selectbox("Role", ["user", "admin"],
                                            index=0 if current_role == "user" else 1,
                                            key=f"role_{i}")
                    if new_role != current_role:
                        if st.button("Update Role", key=f"update_{i}"):
                            success, message = update_user_role(user['username'], new_role)
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                with col3:
                    created_date = user.get('created_at', 'Unknown')
                    if created_date != 'Unknown':
                        try:
                            created_date = datetime.datetime.fromisoformat(created_date).strftime("%Y-%m-%d")
                        except:
                            created_date = 'Unknown'
                    st.write(f"Created: {created_date}")
                with col4:
                    if user['username'] != st.session_state.get("username"):
                        if st.button("Delete", key=f"delete_{i}", type="secondary"):
                            success, message = delete_user(user['username'])
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                    else:
                        st.write("*(Current User)*")
                st.divider()
        st.markdown("</div>", unsafe_allow_html=True)

    with tab2:
        logs = st.session_state.activity_log
        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### Activity Log")
        if not logs:
            st.info("No activity logged yet.")
        else:
            import pandas as pd
            df_logs = pd.DataFrame(logs)
            if 'timestamp' in df_logs.columns:
                df_logs['timestamp'] = pd.to_datetime(df_logs['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
            st.dataframe(df_logs, use_container_width=True)
            if st.button("Clear All Logs", type="secondary"):
                st.session_state.activity_log = []
                st.success("Activity logs cleared.")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ROUTER
# -------------------------------------------------
page = st.session_state.page

if page == "welcome":
    show_welcome()
elif page == "landing":
    show_landing()
elif page == "operations":
    show_operations()
elif page == "solicitations":
    show_solicitations()
elif page == "survey":
    show_survey()
elif page == "training":
    show_training()
elif page == "tools":
    show_tools()
elif page == "autonomous":
    show_autonomous_agent()
elif page == "admin":
    show_admin()
