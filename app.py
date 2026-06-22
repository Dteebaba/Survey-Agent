import datetime
import json
import hashlib
import threading
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

_DARK_CSS = """
body, .stApp { background-color: #0D1117 !important; color: #E6EDF3 !important; }
[data-testid="stHeader"] { background-color: #0D1117 !important; }
[data-testid="stSidebar"] { background-color: #161B22 !important; color: #E6EDF3 !important; }
[data-testid="stSidebar"] * { color: #E6EDF3 !important; }
.app-card { background: #161B22 !important; border-color: #30363D !important; color: #E6EDF3 !important; }
.app-title, .app-subtitle, .feature-title, .feature-desc { color: #E6EDF3 !important; }
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div { background-color: #21262D !important; color: #E6EDF3 !important; border-color: #30363D !important; }
[data-testid="stDataFrame"] { background-color: #161B22 !important; }
div[data-testid="metric-container"] { background-color: #161B22; border: 1px solid #30363D; border-radius: 8px; padding: 0.75rem; }
.stTabs [data-baseweb="tab-list"] { background-color: #161B22; border-bottom-color: #30363D; }
.stTabs [data-baseweb="tab"] { color: #8B949E !important; }
.stTabs [aria-selected="true"] { color: white !important; }
p, label, .stMarkdown, h1, h2, h3, h4 { color: #E6EDF3 !important; }
.stExpander { background-color: #161B22 !important; border-color: #30363D !important; }
"""

# -------------------------------------------------
# Cached sheet loader — shared across all sessions, refreshes every 10 min
# -------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _fetch_solicitations():
    from google_connector import read_master_sheet
    return read_master_sheet()


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
    st.session_state["dark_mode"] = False
    try:
        from agent_state import sync_from_gist
        sync_from_gist()
    except Exception:
        pass
else:
    st.session_state.setdefault("page", "landing")
    st.session_state.setdefault("results_ready", False)
    st.session_state.setdefault("activity_log", [])
    st.session_state.setdefault("dark_mode", False)

# Inject dark mode CSS if enabled
if st.session_state.get("dark_mode"):
    st.markdown(f"<style>{_DARK_CSS}</style>", unsafe_allow_html=True)

# Sidebar — theme toggle + user info + sign out
with st.sidebar:
    st.write(f"**{st.session_state.get('username', '')}**")
    role_display = "Admin" if st.session_state.get("role") == "admin" else "User"
    st.caption(f"Role: {role_display}")
    st.divider()
    dark_on = st.toggle("🌙 Dark Mode", value=st.session_state.get("dark_mode", False))
    if dark_on != st.session_state.get("dark_mode", False):
        st.session_state["dark_mode"] = dark_on
        st.rerun()
    st.divider()
    if st.button("Sign Out", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


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
    from auth import load_users as _gist_load
    return _gist_load()


def save_users(users):
    # Always update local cache first
    try:
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=4)
    except Exception as e:
        st.error(f"Could not write local users cache: {e}")
        return False

    # Gist is the permanent store — must succeed for changes to survive restarts
    from auth import save_users_to_gist
    if save_users_to_gist(users):
        return True

    st.error(
        "⚠️ User saved locally but **could not sync to Gist** — "
        "changes will be lost on next server restart. "
        "Check that **GIST_ID** and **GH_TOKEN** are set in Streamlit Cloud secrets."
    )
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

def show_welcome():
    st.write("")
    st.write("")
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.title("🦅 Almor LLC")
        st.caption("SBA Service-Disabled Veteran-Owned Small Business")
        st.write("")
        st.subheader("Survey Agent")
        st.write("Federal Opportunity Intelligence Platform")
        st.write("")
        st.write("")
        if st.button("Enter Workspace", use_container_width=True, type="primary"):
            if st.session_state.get("role") == "admin":
                goto("landing")
            else:
                goto("solicitations")


# -------------------------------------------------
# LANDING PAGE  (Operations | Solicitations)
# -------------------------------------------------
def show_landing():
    username = st.session_state.get("username", "User")
    role     = st.session_state.get("role", "user")

    if role != "admin":
        goto("solicitations")
        return

    st.title("🦅 Almor LLC — Survey Agent")
    st.write(f"Welcome back, **{username}**")
    st.divider()

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.subheader("⚙️ Operations")
        st.write("Document assistant, AI analysis tools, autonomous agent, and system management.")
        st.write("")
        if st.button("Open Operations →", use_container_width=True, key="btn_ops"):
            goto("operations")

    with col2:
        st.subheader("📋 Solicitations")
        st.write("Live view of the master opportunity sheet. Browse entries and update bid status.")
        st.write("")
        if st.button("View Solicitations →", use_container_width=True, key="btn_sol"):
            goto("solicitations")


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
        """<div class='feature-card'><div class='feature-title'>Autonomous Agent</div>
        <div class='feature-desc'>Auto-scan Drive for the latest file, filter SDVOSB/SBA opps due in 14 days, append to master sheet.</div>""",
        unsafe_allow_html=True,
    )
    if st.button("Open Autonomous Agent"):
        goto("autonomous")
    st.markdown("</div>", unsafe_allow_html=True)

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


def _purge_expired(df):
    """Identify rows where Due Date is 5+ days past and Progress Report is empty.
    Returns (cleaned_df, list_of_sheet_row_numbers_to_delete).
    Sheet row numbers are 1-indexed with row 1 = header."""
    import pandas as pd
    from datetime import date, timedelta

    if "Due Date" not in df.columns:
        return df, []

    cutoff = date.today() - timedelta(days=5)
    drop_positions = []

    for pos in range(len(df)):
        row = df.iloc[pos]
        if str(row.get("Progress Report", "") or "").strip():
            continue  # has a status — keep it
        due = row.get("Due Date")
        if due is None:
            continue
        try:
            if pd.to_datetime(due).date() < cutoff:
                drop_positions.append(pos)
        except Exception:
            pass

    if not drop_positions:
        return df, []

    # +2: row 1 is the header; iloc pos 0 → sheet row 2
    sheet_rows = [pos + 2 for pos in drop_positions]
    cleaned = df.drop(df.index[drop_positions]).reset_index(drop=True)
    return cleaned, sheet_rows


@st.fragment
def _sol_filter_and_table(df):
    """Fragment: only this section reruns when the filter pill is changed."""
    total = len(df)
    has_prog = "Progress Report" in df.columns

    # ── Per-category counts ───────────────────
    cat_counts = {}
    if has_prog:
        for opt in _PROGRESS_OPTIONS:
            if opt:
                cat_counts[opt] = int((df["Progress Report"] == opt).sum())
    pending = int((df["Progress Report"] == "").sum()) if has_prog else total

    # Metrics row: Total + Pending + one cell per status category
    stat_labels = ["Total", "Pending Review"] + list(cat_counts.keys())
    stat_values = [total, pending] + list(cat_counts.values())
    stat_cols = st.columns(len(stat_labels))
    for col, label, val in zip(stat_cols, stat_labels, stat_values):
        col.metric(label, val)

    # ── Filter pills — label includes live count ──
    pill_options = ["All"] + [
        f"{opt}  ({cat_counts.get(opt, 0)})" for opt in _PROGRESS_OPTIONS if opt
    ]
    active_pill = st.pills(
        "Filter by Progress Report",
        options=pill_options,
        selection_mode="single",
        default="All",
        key="sol_filter",
    ) or "All"

    # Strip the count suffix to get the real status string for filtering
    active_filter = active_pill.split("  (")[0] if active_pill != "All" else "All"

    display_df = df.copy()
    if active_filter != "All" and has_prog:
        display_df = display_df[df["Progress Report"] == active_filter].reset_index(drop=False)
    else:
        display_df = display_df.reset_index(drop=False)

    # Keep original df index so sheet row numbers stay correct
    orig_index = display_df["index"].tolist()
    display_df = display_df.drop(columns=["index"])

    st.caption(
        f"Showing {len(display_df)} of {total} solicitations"
        + (f" — {active_filter}" if active_filter != "All" else "")
    )
    st.caption("Change any Progress Report dropdown — it saves to the master sheet automatically.")

    # ── Column config ─────────────────────────
    _cols = display_df.columns.tolist()
    col_cfg = {}
    if "Solicitation Number" in _cols:
        col_cfg["Solicitation Number"] = st.column_config.TextColumn("Sol. #", width=120)
    if "Title" in _cols:
        col_cfg["Title"] = st.column_config.TextColumn("Title", width=220)
    if "Agency" in _cols:
        col_cfg["Agency"] = st.column_config.TextColumn("Agency", width=140)
    if "Solicitation Date" in _cols:
        col_cfg["Solicitation Date"] = st.column_config.DateColumn("Posted", width=90)
    if "Due Date" in _cols:
        col_cfg["Due Date"] = st.column_config.DateColumn("Due Date", width=90)
    if "Opportunity Type" in _cols:
        col_cfg["Opportunity Type"] = st.column_config.TextColumn("Type", width=110)
    if "Normalized Set Aside" in _cols:
        col_cfg["Normalized Set Aside"] = st.column_config.TextColumn("Set Aside", width=140)
    if "UiLink" in _cols:
        col_cfg["UiLink"] = st.column_config.LinkColumn("Link", display_text="SAM.gov", width=75)
    if "Progress Report" in _cols:
        col_cfg["Progress Report"] = st.column_config.SelectboxColumn(
            "Progress Report",
            options=_PROGRESS_OPTIONS,
            required=False,
            width=160,
        )
    if "Award Date" in _cols:
        col_cfg["Award Date"] = st.column_config.DateColumn("Award", width=90)

    _preferred_order = [
        "Solicitation Number", "Title", "Agency", "Solicitation Date",
        "Due Date", "Opportunity Type", "Normalized Set Aside",
        "Progress Report", "UiLink", "Award Date",
    ]
    column_order = [c for c in _preferred_order if c in _cols]
    editable  = ["Progress Report"] if "Progress Report" in _cols else []
    disabled  = [c for c in _cols if c not in editable]

    edited_df = st.data_editor(
        display_df,
        column_config=col_cfg,
        column_order=column_order,
        disabled=disabled,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=f"sol_editor_{active_filter}",
        height=560,
    )

    # ── Auto-save on change ───────────────────
    original_prog = st.session_state.get("sol_original_progress")
    if original_prog is not None and "Progress Report" in edited_df.columns:
        updates = {}
        for pos, (df_idx, new_val) in enumerate(
            zip(orig_index, edited_df["Progress Report"])
        ):
            old_val = original_prog.iloc[df_idx] if df_idx < len(original_prog) else ""
            if str(new_val or "") != str(old_val or ""):
                updates[df_idx + 2] = str(new_val or "")

        if updates:
            # Optimistic update — visible immediately, no spinner
            full_df = st.session_state["sol_data"].copy()
            for df_idx, new_val in zip(orig_index, edited_df["Progress Report"]):
                full_df.at[df_idx, "Progress Report"] = str(new_val or "")
            st.session_state["sol_data"] = full_df
            st.session_state["sol_original_progress"] = (
                full_df["Progress Report"].copy().reset_index(drop=True)
            )

            _save_result: dict = {}

            def _bg_save(u=updates, r=_save_result):
                try:
                    from google_connector import update_progress_reports
                    r["count"] = update_progress_reports(u)
                    r["ok"] = True
                except Exception as exc:
                    r["error"] = str(exc)

            _t = threading.Thread(target=_bg_save, daemon=True)
            _t.start()
            st.session_state["_sol_save"] = (_t, _save_result)
            log_event("update_progress", "pending", f"{len(updates)} rows queued")
            st.toast("💾 Saving…")


def show_solicitations():
    st.title("📋 Solicitations")
    st.caption("Live view of tracked federal opportunities. Progress Report status auto-saves on change.")

    # Report any completed background save from the previous interaction
    _pending = st.session_state.get("_sol_save")
    if _pending:
        _t, _r = _pending
        if not _t.is_alive():
            st.session_state.pop("_sol_save", None)
            if _r.get("ok"):
                st.toast(f"✅ {_r['count']} status(es) saved to sheet", icon="✅")
            elif _r.get("error"):
                st.toast(f"❌ Save failed: {_r['error']}", icon="❌")

    col_back, col_refresh, col_status, col_spacer = st.columns([2, 2, 3, 3])
    with col_back:
        if st.session_state.get("role") == "admin":
            if st.button("← Back to Home"):
                goto("landing")
    with col_refresh:
        if st.button("🔄 Refresh from Sheet"):
            _fetch_solicitations.clear()
            st.session_state.pop("sol_data", None)
            st.session_state.pop("sol_original_progress", None)
            st.session_state["sol_status"] = "loading"
            st.rerun()

    # ── Load data (serve from memory cache, fetch from Drive only on cold start) ──
    sheet_status = st.session_state.get("sol_status", "idle")
    status_placeholder = col_status.empty()

    if "sol_data" not in st.session_state:
        status_placeholder.info("⏳ Loading sheet…")
        try:
            df = _fetch_solicitations()

            # Auto-purge rows that are 5+ days past due with no status
            df, expired_rows = _purge_expired(df)
            if expired_rows:
                def _bg_delete(rows=expired_rows):
                    try:
                        from google_connector import delete_expired_rows
                        delete_expired_rows(rows)
                        _fetch_solicitations.clear()
                    except Exception:
                        pass
                threading.Thread(target=_bg_delete, daemon=True).start()
                st.toast(f"🗑️ Auto-removed {len(expired_rows)} expired row(s) with no status")

            st.session_state["sol_data"] = df
            st.session_state["sol_original_progress"] = (
                df["Progress Report"].copy().reset_index(drop=True)
                if "Progress Report" in df.columns else None
            )
            st.session_state["sol_status"] = "updated"
            status_placeholder.success("✅ Up to date")
        except Exception as e:
            status_placeholder.empty()
            st.error(f"Failed to load sheet: {e}")
            return
    else:
        if sheet_status == "updated":
            status_placeholder.success("✅ Up to date")
        elif sheet_status == "loading":
            status_placeholder.info("⏳ Waiting to update…")
        else:
            status_placeholder.caption("Showing cached data")

    df = st.session_state["sol_data"]

    if df.empty:
        st.info("No solicitations found in the master sheet yet.")
        return

    _sol_filter_and_table(df)


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
            + datetime.fromisoformat(last_entry["timestamp"]).strftime("%b %d, %Y")
        )
    else:
        last_run_label = "Never"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.caption("Last Run")
        st.write(last_run_label)
    with c2:
        st.caption("Last File Processed")
        st.write(_fmt(s["last_file_processed"]))
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

        col_btn, col_reset, col_dv, col_sol = st.columns([3, 2, 2, 2])
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
        with col_sol:
            if st.button("📋 View Solicitations", type="secondary", use_container_width=True,
                         help="Go to the Solicitations sheet"):
                goto("solicitations")

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
                        st.session_state["sol_just_updated"] = True
                    else:
                        names = ", ".join(
                            f["name"] for f in summary.get("processed_files", [])
                        )
                        rows  = summary["total_rows_added"]
                        result_box.success(
                            f"✅ **{rows} rows** appended from: {names}"
                        )
                        # Bust cache so solicitations reloads fresh data from Drive
                        _fetch_solicitations.clear()
                        st.session_state.pop("sol_data", None)
                        st.session_state.pop("sol_original_progress", None)
                        st.session_state["sol_just_updated"] = True

                    log_event(
                        "autonomous_pipeline",
                        "success" if not summary["errors"] else "error",
                        f"files={summary['files_checked']}, rows={summary['total_rows_added']}",
                    )

                except Exception as e:
                    progress_box.empty()
                    result_box.error(f"Pipeline failed: {e}")

        # View solicitations shortcut after a successful run
        if st.session_state.get("sol_just_updated"):
            st.write("")
            _, btn_col, _ = st.columns([2, 3, 2])
            with btn_col:
                if st.button("📋 View Updated Solicitations →", use_container_width=True, type="primary"):
                    st.session_state.pop("sol_just_updated", None)
                    goto("solicitations")

        # Last run detail card
        if last_entry:
            st.divider()
            st.markdown("#### Last Run Report")

            ts = datetime.fromisoformat(last_entry["timestamp"]).strftime("%B %d, %Y  %H:%M UTC")
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

            st.write(f"**Status:** {status_label}")
            st.write(f"**Message:** {last_entry.get('message', '—')}")

            pf = last_entry.get("processed_files", [])
            if pf:
                st.write("**Files processed in this run:**")
                pf_rows = []
                for item in pf:
                    if isinstance(item, dict):
                        pf_rows.append({"Source Sheet": item["name"], "Rows Added": item.get("rows_added", 0)})
                    else:
                        pf_rows.append({"Source Sheet": item, "Rows Added": "—"})
                st.dataframe(pd.DataFrame(pf_rows), use_container_width=True, hide_index=True)

            errs = last_entry.get("errors", [])
            if errs:
                st.write("**Errors:**")
                for err in errs:
                    st.error(err)

    # ── Tab 2: Run History ────────────────────────────────────
    with tab_history:
        run_log = s.get("run_log", [])

        if not run_log:
            st.info("No run history yet. The log will fill up after the first pipeline run.")
        else:
            st.write(f"**{len(run_log)} run(s) recorded** — most recent first")
            st.write("")

            for entry in run_log:   # already most-recent-first
                ts = entry.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%b %d, %Y  %H:%M UTC")
                except Exception:
                    ts_fmt = ts

                status_icon = {
                    "success":      "✅ Success",
                    "error":        "❌ Error",
                    "no_new_files": "ℹ️ No New Files",
                }.get(entry.get("status", ""), "—")

                trig    = entry.get("triggered_by", "?").capitalize()
                f_done  = entry.get("files_processed", 0)
                rows_added = entry.get("rows_added", 0)
                label   = f"{status_icon}  ·  {ts_fmt}  ·  {trig}  ·  {f_done} file(s)  ·  {rows_added} rows added"

                with st.expander(label, expanded=False):
                    msg = entry.get("message", "")
                    if msg:
                        st.write(f"**Message:** {msg}")

                    pf = entry.get("processed_files", [])
                    if pf:
                        st.write("**Source Sheets processed:**")
                        pf_rows = []
                        for item in pf:
                            if isinstance(item, dict):
                                pf_rows.append({"Source Sheet": item["name"], "Rows Added": item.get("rows_added", 0)})
                            else:
                                pf_rows.append({"Source Sheet": item, "Rows Added": "—"})
                        st.dataframe(pd.DataFrame(pf_rows), use_container_width=True, hide_index=True)

                    errs = entry.get("errors", [])
                    if errs:
                        st.write("**Errors:**")
                        for err in errs:
                            st.error(err)

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Files Checked",    entry.get("files_checked", 0))
                    c2.metric("Files Processed",  f_done)
                    c3.metric("Rows Added",       rows_added)

            st.write("")
            run_log_export = []
            for entry in run_log:
                pf = entry.get("processed_files", [])
                sheets = ", ".join(
                    item["name"] if isinstance(item, dict) else item for item in pf
                )
                run_log_export.append({
                    "Timestamp (UTC)":  entry.get("timestamp", ""),
                    "Triggered By":     entry.get("triggered_by", ""),
                    "Status":           entry.get("status", ""),
                    "Files Checked":    entry.get("files_checked", 0),
                    "Files Processed":  entry.get("files_processed", 0),
                    "Rows Added":       entry.get("rows_added", 0),
                    "Source Sheets":    sheets,
                    "Message":          entry.get("message", ""),
                    "Errors":           "; ".join(entry.get("errors", [])),
                })
            col_dl, _ = st.columns([2, 5])
            with col_dl:
                csv_bytes = pd.DataFrame(run_log_export).to_csv(index=False).encode()
                st.download_button("Download Run Log CSV", csv_bytes, "run_history.csv", mime="text/csv")

    # ── Tab 3: Processed Files ────────────────────────────────
    with tab_files:
        pf_list = s.get("processed_files", [])

        if not pf_list:
            st.info("No files processed yet.")
        else:
            rows_pf = []
            for pf in reversed(pf_list):   # most recent first
                ts = pf.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%b %d, %Y  %H:%M UTC")
                except Exception:
                    ts_fmt = ts
                status = pf.get("status", "ok").lower()
                rows_pf.append({
                    "Processed At (UTC)": ts_fmt,
                    "Source Sheet":       pf.get("name", ""),
                    "Rows Added":         pf.get("rows_added", 0),
                    "Status":             "✅ OK" if status == "ok" else "❌ Error",
                })

            df_pf = pd.DataFrame(rows_pf)
            total_rows = s.get("total_rows_added", 0)
            c1, c2 = st.columns(2)
            c1.metric("Total Source Sheets Processed", len(df_pf))
            c2.metric("Total Rows Ever Added to Master Sheet", total_rows)
            st.write("")
            st.dataframe(
                df_pf,
                use_container_width=True,
                hide_index=True,
                height=500,
                column_config={
                    "Processed At (UTC)": st.column_config.TextColumn(width="medium"),
                    "Source Sheet":       st.column_config.TextColumn(width="large"),
                    "Rows Added":         st.column_config.NumberColumn(width="small"),
                    "Status":             st.column_config.TextColumn(width="small"),
                },
            )
            col_dl2, _ = st.columns([2, 5])
            with col_dl2:
                csv2 = df_pf.to_csv(index=False).encode()
                st.download_button("Download File Log CSV", csv2, "processed_files.csv", mime="text/csv")

    # ── Tab 4: Error Log ──────────────────────────────────────
    with tab_errors:
        all_errors = s.get("recent_errors", [])

        if not all_errors:
            st.success("No errors recorded.")
        else:
            for err in reversed(all_errors):
                ts = err.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%b %d, %Y  %H:%M UTC")
                except Exception:
                    ts_fmt = ts
                st.error(f"[{ts_fmt}]  {err.get('message', '')}")

    # ── Tab 5: Configuration ──────────────────────────────────
    with tab_cfg:
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1bSGpFbEW09jAq6pdn1i_WO8RUAa3DPUJ")
        sheet_id  = os.getenv("GOOGLE_SHEETS_ID",       "151jig9_3v-__dHfk7TksitJYONDMOLQV")

        st.subheader("How the Agent Works")
        st.write(
            "Every night at **10 PM ET**, the agent automatically scans your Google Drive folder "
            "for new opportunity files. It filters for SDVOSB, SDVOSBC, and SBA set-aside solicitations "
            "with due dates within the next 14 days, then appends qualifying rows to the master sheet. "
            "Files already processed are always skipped — no duplicates, ever."
        )
        st.write(
            "You can also trigger a manual run at any time using the **Run Latest Update** button "
            "on the Run / Control tab. Manual runs and scheduled runs both write to the same master sheet."
        )
        st.write(
            "Run history and file tracking are saved persistently — the dashboard shows a full record "
            "of every run even after a server restart."
        )

        st.divider()
        st.subheader("Quick Links")
        st.write(f"- **Google Drive Folder** (source files): [Open Folder](https://drive.google.com/drive/folders/{folder_id})")
        st.write(f"- **Master Sheet** (output): [Open Sheet](https://docs.google.com/spreadsheets/d/{sheet_id})")
        st.write("- **Filter:** SDVOSB / SDVOSBC / SBA set-asides · Due within **14 days**")
        st.write("- **Automatic schedule:** Every night at **10:00 PM ET**")

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

        st.subheader("Current Users")
        users = load_users()
        if not users:
            st.info("No users found. Add the first user above.")
        else:
            st.caption(f"{len(users)} registered user(s) — accounts are permanent and never deleted")
            st.write("")
            for i, user in enumerate(users):
                uname = user['username']
                current_role = user.get('role', 'user')
                created = user.get('created_at', '')
                try:
                    created = datetime.datetime.fromisoformat(created).strftime("%b %d, %Y")
                except Exception:
                    created = created[:10] if created else "—"

                with st.expander(f"**{uname}** — {current_role.capitalize()}  ·  Added {created}", expanded=False):
                    c1, c2 = st.columns([2, 3])
                    with c1:
                        new_role = st.selectbox(
                            "Role",
                            ["user", "admin"],
                            index=0 if current_role == "user" else 1,
                            key=f"role_{i}",
                            help="User: Solicitations only  |  Admin: Full access",
                        )
                    with c2:
                        st.write("")
                        st.write("")
                        if uname != st.session_state.get("username"):
                            if st.button("Save Role Change", key=f"update_{i}", use_container_width=True):
                                success, message = update_user_role(uname, new_role)
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
                        else:
                            st.info("This is your own account.")

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
_role = st.session_state.get("role", "user")

# Regular users can only access welcome, landing (redirects them), and solicitations
_USER_PAGES = {"welcome", "landing", "solicitations"}
if _role != "admin" and page not in _USER_PAGES:
    goto("solicitations")

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
