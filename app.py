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

_WORKSPACE_CSS = """
<style>
.workspace-hero {
    position: relative;
    overflow: hidden;
    padding: 1.35rem 1.55rem;
    margin: .15rem 0 1rem;
    border: 1px solid rgba(201,162,39,.30);
    border-radius: 18px;
    background: linear-gradient(130deg, #101a2b 0%, #17263c 58%, #1e293b 100%);
    box-shadow: 0 12px 34px rgba(3,8,20,.30), 0 0 28px rgba(201,162,39,.08);
}
.workspace-hero::after {
    content:""; position:absolute; width:190px; height:190px; right:-55px; top:-85px;
    border-radius:50%; background:#d4af37; filter:blur(65px); opacity:.16;
}
.workspace-kicker { margin:0 0 .35rem; color:#e8c547; font-size:.72rem; font-weight:800; letter-spacing:.15em; text-transform:uppercase; }
.workspace-title { margin:0; color:#fff; font-size:1.75rem; font-weight:900; letter-spacing:-.02em; }
.workspace-sub { margin:.4rem 0 0; color:rgba(255,255,255,.62); font-size:.88rem; max-width:760px; line-height:1.55; }
.workflow-strip { display:flex; flex-wrap:wrap; gap:.55rem; margin:.15rem 0 1rem; }
.workflow-step { padding:.5rem .75rem; border-radius:999px; border:1px solid rgba(255,255,255,.10); background:rgba(17,24,39,.72); color:#d9e2ef; font-size:.78rem; }
.workflow-step b { color:#e8c547; margin-right:.3rem; }
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
    border:1px solid rgba(201,162,39,.20); border-radius:14px; overflow:hidden;
    box-shadow:0 10px 28px rgba(0,0,0,.16), 0 0 20px rgba(201,162,39,.045);
}
div[data-testid="stMetric"] { border:1px solid rgba(201,162,39,.14); border-radius:13px; padding:.5rem; background:linear-gradient(145deg,rgba(23,38,60,.76),rgba(15,23,42,.76)); }
div[data-testid="stButton"] button[kind="primary"] {
    background:linear-gradient(135deg,#b88a12,#e8c547) !important; color:#111827 !important;
    border:0 !important; box-shadow:0 6px 20px rgba(201,162,39,.28) !important; font-weight:800 !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover { transform:translateY(-1px); box-shadow:0 9px 26px rgba(201,162,39,.40) !important; }
</style>
"""


def _workspace_header(kicker: str, title: str, subtitle: str, steps: list[str]):
    """Render the shared workspace hero and compact process guide."""
    st.markdown(_WORKSPACE_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""<div class="workspace-hero">
        <p class="workspace-kicker">{kicker}</p>
        <p class="workspace-title">{title}</p>
        <p class="workspace-sub">{subtitle}</p>
        </div>""",
        unsafe_allow_html=True,
    )
    chips = "".join(
        f'<span class="workflow-step"><b>{index}</b>{label}</span>'
        for index, label in enumerate(steps, 1)
    )
    st.markdown(f'<div class="workflow-strip">{chips}</div>', unsafe_allow_html=True)


def _workspace_guide(kind: str):
    """Optional, reopenable help; users may dismiss the automatic first-visit card."""
    dismissed_key = f"guide_dismissed_{kind}"
    labels = {
        "opportunities": [
            ("Search all columns", "Type any part of an ID, title, agency, date, set-aside, or link."),
            ("Set Aside / Due toggle", "Narrow the pool without changing the underlying worksheet."),
            ("Select", "Tick one or several qualified solicitation rows."),
            ("Shortlist selected", "Moves selected rows safely into the shared active-work sheet."),
            ("View Shortlisted", "Opens team assignments, progress, and award tracking."),
        ],
        "shortlisted": [
            ("Search all columns", "Find work by ID, title, agency, assignee, progress, or award status."),
            ("Status pills", "Focus the table on a processing stage or urgent deadline."),
            ("Progress Report", "Update the current bid-processing stage; it saves automatically."),
            ("Assigned To", "Choose the team member responsible for the solicitation."),
            ("Award Status", "Record submitted, awarded, rejected, or pending outcomes."),
        ],
    }
    with st.popover("❔ Quick guide", use_container_width=False):
        st.markdown("#### What each control does")
        for name, description in labels[kind]:
            st.markdown(f"**{name}** — {description}")

    if not st.session_state.get(dismissed_key, False):
        with st.container(border=True):
            st.markdown("#### 👋 Quick start")
            st.caption("A short guide for this workspace. You can reopen it later with Quick guide.")
            for name, description in labels[kind][:4]:
                st.markdown(f"- **{name}:** {description}")
            if st.button("Got it — hide this guide", key=f"dismiss_{kind}"):
                st.session_state[dismissed_key] = True
                st.rerun()

# -------------------------------------------------
# Shared workspaces use a short TTL so team changes appear promptly. Manual
# refresh and every successful write also clear the relevant cache immediately.
# -------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def _fetch_solicitations():
    from google_connector import read_master_sheet
    return read_master_sheet()

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_urgent():
    from google_connector import read_urgent_tab
    return read_urgent_tab()

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_shortlisted():
    from google_connector import read_shortlisted_sheet
    return read_shortlisted_sheet()


# -------------------------------------------------
# AUTH + SESSION STATE
# -------------------------------------------------
check_access()

# First run after login: sync state from Gist then show welcome splash
if "app_initialized" not in st.session_state:
    st.session_state["app_initialized"] = True
    # Restore page from URL query param (survives browser refresh).
    # On a fresh login the param won't be set so we land on "welcome".
    _restore_page = st.query_params.get("page", "")
    st.session_state["page"] = _restore_page if _restore_page else "welcome"
    st.session_state["results_ready"] = False
    st.session_state["activity_log"] = []
    st.session_state["dark_mode"] = False
    try:
        import threading as _threading
        from agent_state import sync_from_gist, log_user_activity
        _threading.Thread(target=sync_from_gist, daemon=True).start()
        if not _restore_page:  # only log login event on fresh login, not refresh
            log_user_activity(st.session_state.get("username", "unknown"), "login")
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
    st.caption("WORKSPACES")
    if st.button("🔎 Find Opportunities", use_container_width=True, key="side_opportunities"):
        st.session_state.page = "solicitations"
        st.query_params["page"] = "solicitations"
        st.rerun()
    if st.button("⭐ Shortlisted", use_container_width=True, key="side_shortlisted"):
        st.session_state.page = "shortlisted"
        st.query_params["page"] = "shortlisted"
        st.rerun()
    if st.button("⌂ Home", use_container_width=True, key="side_home"):
        st.session_state.page = "landing"
        st.query_params["page"] = "landing"
        st.rerun()
    st.divider()
    dark_on = st.toggle("🌙 Dark Mode", value=st.session_state.get("dark_mode", False))
    if dark_on != st.session_state.get("dark_mode", False):
        st.session_state["dark_mode"] = dark_on
        st.rerun()
    st.divider()
    if st.button("Sign Out", use_container_width=True):
        from auth import clear_auth_cookie
        try:
            from agent_state import log_user_activity
            log_user_activity(st.session_state.get("username", "unknown"), "logout")
        except Exception:
            pass
        clear_auth_cookie()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


def goto(page: str):
    st.session_state.page = page
    try:
        st.query_params["page"] = page
    except Exception:
        pass
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
    target = next((u for u in users if u['username'] == username), None)
    if target and target.get('role') == 'admin':
        return False, "Cannot remove an admin account. Downgrade their role to 'user' first, then remove."
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
    st.markdown("""
    <style>
    /* Dark animated background for welcome page main area */
    [data-testid="stAppViewContainer"] > .main {
        background: linear-gradient(-45deg, #0B1120, #112240, #0F3460, #1A1A2E);
        background-size: 400% 400%;
        animation: welcomeBG 14s ease infinite;
        min-height: 100vh;
    }
    @keyframes welcomeBG {
        0%   { background-position: 0%   50%; }
        50%  { background-position: 100% 50%; }
        100% { background-position: 0%   50%; }
    }

    /* Floating eagle */
    .welcome-eagle {
        font-size: 5rem;
        display: block;
        text-align: center;
        animation: eagleBob 3s ease-in-out infinite;
        filter: drop-shadow(0 8px 24px rgba(201,162,39,0.4));
        margin-bottom: 0.5rem;
    }
    @keyframes eagleBob {
        0%,100% { transform: translateY(0px) rotate(-2deg); }
        50%      { transform: translateY(-14px) rotate(2deg); }
    }

    /* Brand text entrance */
    .welcome-brand {
        text-align: center;
        animation: fadeInUp 0.8s ease both;
    }
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(24px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .welcome-company {
        color: #FFFFFF;
        font-size: 2.2rem;
        font-weight: 900;
        letter-spacing: 0.14em;
        margin: 0;
        text-shadow: 0 2px 20px rgba(0,0,0,0.5);
    }
    .welcome-product {
        color: #C9A227;
        font-size: 1.1rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        margin: 0.4rem 0 0.2rem;
    }
    .welcome-tagline {
        color: rgba(255,255,255,0.35);
        font-size: 0.82rem;
        letter-spacing: 0.06em;
        margin: 0 0 0.6rem;
    }
    .welcome-badge {
        display: inline-block;
        background: rgba(201,162,39,0.12);
        border: 1px solid rgba(201,162,39,0.35);
        color: #C9A227;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        padding: 0.28rem 0.85rem;
        border-radius: 20px;
        text-transform: uppercase;
        margin-bottom: 2.2rem;
    }

    /* Pulsing guide tooltip */
    .welcome-guide {
        text-align: center;
        animation: fadeInUp 0.8s ease 0.6s both;
        margin-bottom: 0.6rem;
    }
    .guide-arrow {
        display: inline-block;
        color: rgba(255,255,255,0.5);
        font-size: 0.8rem;
        letter-spacing: 0.08em;
        animation: guidePulse 2s ease-in-out infinite;
    }
    .guide-dot {
        display: inline-block;
        width: 8px; height: 8px;
        border-radius: 50%;
        background: #C9A227;
        margin-right: 8px;
        animation: dotPulse 2s ease-in-out infinite;
        vertical-align: middle;
    }
    @keyframes guidePulse {
        0%,100% { opacity: 0.5; transform: translateY(0); }
        50%      { opacity: 1;   transform: translateY(4px); }
    }
    @keyframes dotPulse {
        0%,100% { transform: scale(1);    opacity: 0.7; }
        50%      { transform: scale(1.4); opacity: 1;   }
    }

    /* Enter button */
    .welcome-btn-wrap .stButton > button {
        background: linear-gradient(135deg, #C9A227, #E8C547) !important;
        color: #0B1120 !important;
        border: none !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        font-size: 1rem !important;
        letter-spacing: 0.06em !important;
        padding: 0.8rem 2rem !important;
        box-shadow: 0 6px 28px rgba(201,162,39,0.4) !important;
        transition: all 0.25s ease !important;
        animation: fadeInUp 0.8s ease 0.9s both;
    }
    .welcome-btn-wrap .stButton > button:hover {
        transform: translateY(-3px) !important;
        box-shadow: 0 12px 36px rgba(201,162,39,0.55) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.write("")
    st.write("")
    _, center, _ = st.columns([1, 1.4, 1])
    with center:
        # Animated eagle
        st.markdown('<span class="welcome-eagle">🦅</span>', unsafe_allow_html=True)

        # Brand block
        st.markdown("""
        <div class="welcome-brand">
            <p class="welcome-company">ALMOR LLC</p>
            <p class="welcome-product">Survey Agent</p>
            <p class="welcome-tagline">Federal Opportunity Intelligence Platform</p>
            <span class="welcome-badge">★ SBA Service-Disabled Veteran-Owned</span>
        </div>
        """, unsafe_allow_html=True)

        # Pulsing guide
        st.markdown("""
        <div class="welcome-guide">
            <span class="guide-dot"></span>
            <span class="guide-arrow">click below to enter your workspace ↓</span>
        </div>
        """, unsafe_allow_html=True)

        # Enter button
        st.markdown('<div class="welcome-btn-wrap">', unsafe_allow_html=True)
        if st.button("Enter Workspace →", use_container_width=True, type="primary"):
            goto("landing")
        st.markdown('</div>', unsafe_allow_html=True)

        st.write("")
        st.markdown(
            "<p style='text-align:center; color:rgba(255,255,255,0.2); font-size:0.75rem; margin:0;'>"
            "Not you? &nbsp;"
            "</p>",
            unsafe_allow_html=True,
        )
        if st.button("Sign Out", use_container_width=True, key="welcome_signout"):
            from auth import clear_auth_cookie
            clear_auth_cookie()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


# -------------------------------------------------
# LANDING PAGE  (Operations | Solicitations)
# -------------------------------------------------
def show_landing():
    username = st.session_state.get("username", "User")
    role     = st.session_state.get("role", "user")

    st.markdown("""
    <style>
    .landing-hero {
        padding: 1.8rem 0 0.5rem;
        animation: fadeInUp 0.6s ease both;
    }
    @keyframes fadeInUp {
        from { opacity:0; transform:translateY(20px); }
        to   { opacity:1; transform:translateY(0);    }
    }
    .landing-greeting {
        color: rgba(255,255,255,0.4);
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin: 0 0 0.25rem;
    }
    .landing-title {
        color: #FFFFFF;
        font-size: 2rem;
        font-weight: 900;
        margin: 0 0 0.4rem;
        letter-spacing: 0.02em;
    }
    .landing-sub {
        color: rgba(255,255,255,0.4);
        font-size: 0.88rem;
        margin: 0;
    }

    /* Hub cards */
    .hub-card {
        background: linear-gradient(155deg, #1C2A3E 0%, #111827 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 22px;
        padding: 2.4rem 2rem 1.4rem;
        min-height: 280px;
        position: relative;
        overflow: hidden;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
        animation: fadeInUp 0.7s ease both;
    }
    .hub-card:hover {
        transform: translateY(-6px);
        box-shadow: 0 24px 56px rgba(0,0,0,0.5);
        border-color: rgba(255,255,255,0.18);
    }
    .hub-card::before {
        content:"";
        position:absolute;
        top:0; left:0; right:0;
        height:4px;
        border-radius:22px 22px 0 0;
    }
    .hub-card.ops::before  { background: linear-gradient(90deg,#3B82F6,#60A5FA); }
    .hub-card.sol::before  { background: linear-gradient(90deg,#C9A227,#E8C547); }
    .hub-card::after {
        content:"";
        position:absolute;
        width:180px; height:180px;
        border-radius:50%;
        bottom:-50px; right:-50px;
        opacity:0.06;
        filter:blur(40px);
    }
    .hub-card.ops::after { background:#3B82F6; }
    .hub-card.sol::after { background:#C9A227; }

    .hub-icon {
        font-size: 3rem;
        display: block;
        margin-bottom: 1.1rem;
        animation: iconFloat 4s ease-in-out infinite;
    }
    .hub-card.sol .hub-icon { animation-delay: -2s; }
    @keyframes iconFloat {
        0%,100% { transform: translateY(0); }
        50%      { transform: translateY(-6px); }
    }
    .hub-card-title {
        color: #FFFFFF;
        font-size: 1.3rem;
        font-weight: 800;
        margin: 0 0 0.5rem;
    }
    .hub-card-desc {
        color: rgba(255,255,255,0.45);
        font-size: 0.84rem;
        line-height: 1.6;
        margin: 0 0 1.4rem;
    }

    /* Hub card buttons */
    .hub-ops-btn .stButton > button {
        background: linear-gradient(135deg,#3B82F6,#60A5FA) !important;
        color: #fff !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 0.88rem !important;
        padding: 0.65rem 1.2rem !important;
        box-shadow: 0 4px 18px rgba(59,130,246,0.35) !important;
        transition: all 0.22s !important;
    }
    .hub-ops-btn .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 28px rgba(59,130,246,0.5) !important;
    }
    .hub-sol-btn .stButton > button {
        background: linear-gradient(135deg,#C9A227,#E8C547) !important;
        color: #0B1120 !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 0.88rem !important;
        padding: 0.65rem 1.2rem !important;
        box-shadow: 0 4px 18px rgba(201,162,39,0.35) !important;
        transition: all 0.22s !important;
    }
    .hub-sol-btn .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 28px rgba(201,162,39,0.5) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Hero header ──────────────────────────────
    hdr_col, signout_col = st.columns([5, 1])
    with hdr_col:
        st.markdown(f"""
        <div class="landing-hero">
            <p class="landing-greeting">Welcome back, {username}</p>
            <p class="landing-title">Where would you like to go?</p>
            <p class="landing-sub">Choose a workspace to get started.</p>
        </div>
        """, unsafe_allow_html=True)
    with signout_col:
        st.write("")
        st.write("")
        if st.button("Sign Out", use_container_width=True, key="landing_signout"):
            from auth import clear_auth_cookie
            clear_auth_cookie()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    st.write("")

    # ── Two hub cards ────────────────────────────
    c1, c2, c3 = st.columns(3, gap="large")

    with c1:
        st.markdown("""
        <div class="hub-card ops">
            <span class="hub-icon">⚙️</span>
            <p class="hub-card-title">Operations</p>
            <p class="hub-card-desc">
                Run the autonomous pipeline, manage documents with AI, access training,
                and configure the system from one place.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div class="hub-ops-btn">', unsafe_allow_html=True)
        if st.button("Open Operations →", use_container_width=True, key="btn_ops"):
            goto("operations")
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="hub-card sol">
            <span class="hub-icon">📋</span>
            <p class="hub-card-title">Find Opportunities</p>
            <p class="hub-card-desc">
                Search the incoming opportunity pool and select qualified solicitations
                for team processing.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div class="hub-sol-btn">', unsafe_allow_html=True)
        if st.button("Find Opportunities →", use_container_width=True, key="btn_sol"):
            goto("solicitations")
        st.markdown('</div>', unsafe_allow_html=True)

    with c3:
        st.markdown("""
        <div class="hub-card sol">
            <span class="hub-icon">⭐</span>
            <p class="hub-card-title">Shortlisted</p>
            <p class="hub-card-desc">
                Open the shared active-work queue to assign owners, track progress,
                and record award outcomes.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div class="hub-sol-btn">', unsafe_allow_html=True)
        if st.button("View Shortlisted →", use_container_width=True, key="btn_shortlisted"):
            goto("shortlisted")
        st.markdown('</div>', unsafe_allow_html=True)


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
# OPERATIONS PAGE
# -------------------------------------------------
_OPS_CSS = """
<style>
/* ── Operations page header ── */
.ops-header {
    margin-bottom: 0.25rem;
}
.ops-header-title {
    font-size: 2rem;
    font-weight: 900;
    color: #FFFFFF;
    letter-spacing: 0.02em;
    margin: 0;
}
.ops-header-sub {
    color: rgba(255,255,255,0.45);
    font-size: 0.9rem;
    margin: 0.3rem 0 0;
}

/* ── Card shell ── */
.ops-card {
    background: linear-gradient(160deg, #1C2A3E 0%, #111827 100%);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    padding: 1.8rem 1.6rem 0.8rem;
    min-height: 210px;
    position: relative;
    overflow: hidden;
    transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
}
.ops-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 20px 48px rgba(0,0,0,0.45);
    border-color: rgba(255,255,255,0.18);
}

/* ── Coloured top accent bar ── */
.ops-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    border-radius: 20px 20px 0 0;
}
.ops-card.blue::before   { background: linear-gradient(90deg, #3B82F6, #60A5FA); }
.ops-card.purple::before { background: linear-gradient(90deg, #8B5CF6, #A78BFA); }
.ops-card.green::before  { background: linear-gradient(90deg, #10B981, #34D399); }
.ops-card.amber::before  { background: linear-gradient(90deg, #F59E0B, #FCD34D); }
.ops-card.red::before    { background: linear-gradient(90deg, #EF4444, #F87171); }

/* ── Soft glow blob in card corner ── */
.ops-card::after {
    content: "";
    position: absolute;
    width: 120px; height: 120px;
    border-radius: 50%;
    bottom: -30px; right: -30px;
    opacity: 0.07;
    filter: blur(30px);
}
.ops-card.blue::after   { background: #3B82F6; }
.ops-card.purple::after { background: #8B5CF6; }
.ops-card.green::after  { background: #10B981; }
.ops-card.amber::after  { background: #F59E0B; }
.ops-card.red::after    { background: #EF4444; }

/* ── Icon badge ── */
.ops-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 52px; height: 52px;
    border-radius: 14px;
    font-size: 1.6rem;
    margin-bottom: 1rem;
}
.ops-card.blue   .ops-icon { background: rgba(59,130,246,0.15); }
.ops-card.purple .ops-icon { background: rgba(139,92,246,0.15); }
.ops-card.green  .ops-icon { background: rgba(16,185,129,0.15); }
.ops-card.amber  .ops-icon { background: rgba(245,158,11,0.15); }
.ops-card.red    .ops-icon { background: rgba(239,68,68,0.15); }

/* ── Card text ── */
.ops-card-title {
    color: #FFFFFF;
    font-size: 1.05rem;
    font-weight: 700;
    margin: 0 0 0.4rem;
    letter-spacing: 0.01em;
}
.ops-card-desc {
    color: rgba(255,255,255,0.45);
    font-size: 0.8rem;
    line-height: 1.55;
    margin: 0 0 1.1rem;
}

/* ── Card launch buttons ── */
div[data-testid="stButton"] > button[kind="secondary"] {
    background: rgba(255,255,255,0.06) !important;
    color: rgba(255,255,255,0.8) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 10px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 0.45rem 1rem !important;
    transition: all 0.2s !important;
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    background: rgba(255,255,255,0.12) !important;
    border-color: rgba(255,255,255,0.25) !important;
    color: #FFFFFF !important;
}
</style>
"""


def _ops_card(color: str, icon: str, title: str, desc: str):
    st.markdown(
        f"""
        <div class="ops-card {color}">
            <div class="ops-icon">{icon}</div>
            <div class="ops-card-title">{title}</div>
            <div class="ops-card-desc">{desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_operations():
    st.markdown(_OPS_CSS, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────
    hdr, back_col = st.columns([5, 1])
    with hdr:
        st.markdown(
            """
            <div class="ops-header">
                <p class="ops-header-title">Operations</p>
                <p class="ops-header-sub">
                    AI-powered tools for managing federal opportunity intelligence.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with back_col:
        st.write("")
        if st.button("← Home", use_container_width=True):
            goto("landing")

    st.write("")

    # ── Row 1: three main tools ───────────────────
    c1, c2, c3 = st.columns(3, gap="medium")

    with c1:
        _ops_card(
            "blue", "🤖",
            "Autonomous Agent",
            "Nightly Drive scan — filters SDVOSB/SBA opportunities and appends new rows to the master sheet automatically.",
        )
        if st.button("Launch →", key="op_autonomous", use_container_width=True):
            goto("autonomous")

    with c2:
        _ops_card(
            "purple", "📄",
            "Document Assistant",
            "Upload a raw SAM.gov export, normalize columns, apply AI filters, and download a clean output file.",
        )
        if st.button("Launch →", key="op_survey", use_container_width=True):
            goto("survey")

    with c3:
        _ops_card(
            "green", "🎓",
            "Training",
            "Step-by-step tutorials on SAM.gov searches, set-aside codes, and how to get the most from every tool.",
        )
        if st.button("Launch →", key="op_training", use_container_width=True):
            goto("training")

    st.write("")

    # ── Row 2: AI Tools for all; Admin Console + Staff for admins only ──
    is_admin = st.session_state.get("role") == "admin"
    if is_admin:
        c4, c5, c6 = st.columns(3, gap="medium")
    else:
        c4, c4b, _ = st.columns(3, gap="medium")

    with c4:
        _ops_card(
            "amber", "🧠",
            "AI Tools",
            "Use specialized AI assistants to score, compare, and summarise federal opportunities in seconds.",
        )
        if st.button("Launch →", key="op_tools", use_container_width=True):
            goto("tools")

    if is_admin:
        with c5:
            _ops_card(
                "red", "⚙️",
                "Admin Console",
                "Create and manage user accounts, assign roles, and monitor system activity logs.",
            )
            if st.button("Launch →", key="op_admin", use_container_width=True):
                goto("admin")

        with c6:
            _ops_card(
                "amber", "👥",
                "Staff",
                "Track user activity: logins, session hours, and progress report updates per user.",
            )
            if st.button("Launch →", key="op_staff", use_container_width=True):
                goto("staff")


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

_AWARD_STATUS_OPTIONS = [
    "",
    "Submitted",
    "Awarded",
    "Rejected",
    "Pending Decision",
]


@st.dialog("Solicitation Details", width="large")
def _opportunity_detail_dialog(row: dict, sol_keys: list, sheet_row: int = 0):
    """Full detail view for one opportunity row. Called from the Opportunities table."""
    sol_num  = str(row.get("Solicitation Number", "") or "").strip()
    title    = str(row.get("Title", "") or "")
    agency   = str(row.get("Agency", "") or "")
    sol_date = str(row.get("Solicitation Date", "") or "")
    due_date = str(row.get("Due Date", "") or "")
    opp_type = str(row.get("Opportunity Type", "") or "")
    set_aside= str(row.get("Normalized Set Aside", "") or "")
    link     = str(row.get("UiLink", "") or "").strip()

    st.markdown(f"### {title or '(No title)'}")
    st.caption(f"Solicitation #{sol_num}" if sol_num else "")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Agency:** {agency or '—'}")
        st.markdown(f"**Posted:** {sol_date or '—'}")
        st.markdown(f"**Due Date:** {due_date or '—'}")
    with c2:
        st.markdown(f"**Type:** {opp_type or '—'}")
        st.markdown(f"**Set Aside:** {set_aside or '—'}")

    if link:
        st.link_button("🔗 Open on SAM.gov", link, use_container_width=True)

    st.divider()
    st.markdown("**What would you like to do with this solicitation?**")

    c_sl, c_skip, c_del = st.columns([2, 1.5, 1.5])
    with c_sl:
        if st.button("⭐ Move to Shortlisted", type="primary", use_container_width=True,
                     key="_dlg_shortlist_btn"):
            if not sol_keys:
                st.error("No key found for this row.")
            else:
                try:
                    with st.spinner("Moving to Shortlisted…"):
                        from google_connector import shortlist_solicitations
                        result = shortlist_solicitations(sol_keys, st.session_state.get("username", "unknown"))
                    try:
                        from agent_state import log_user_activity
                        log_user_activity(
                            st.session_state.get("username", "unknown"),
                            "shortlist", {"count": result["moved"], "solicitations": sol_keys},
                        )
                    except Exception:
                        pass
                    _fetch_solicitations.clear()
                    _fetch_shortlisted.clear()
                    _fetch_urgent.clear()
                    st.session_state.pop("opportunities_data", None)
                    st.session_state.pop("sol_data", None)
                    st.success(f"✅ Moved {result['moved']} solicitation(s) to Shortlisted.")
                    st.session_state["page"] = "shortlisted"
                    st.query_params["page"] = "shortlisted"
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")
    with c_skip:
        if st.button("⏭ Skip for now", use_container_width=True, key="_dlg_skip_btn"):
            st.rerun()
    with c_del:
        if st.button("🗑️ Delete", use_container_width=True, key="_dlg_delete_opp_btn"):
            if sheet_row < 2:
                st.error("Cannot determine row to delete.")
            else:
                try:
                    with st.spinner("Deleting…"):
                        from google_connector import delete_expired_rows, SHEET_TAB_NAME
                        delete_expired_rows([sheet_row], SHEET_TAB_NAME)
                    _fetch_solicitations.clear()
                    st.session_state.pop("opportunities_data", None)
                    st.success("✅ Row deleted from Opportunities.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")


@st.dialog("Shortlisted Record", width="large")
def _shortlisted_detail_dialog(row: dict, sheet_row: int, orig_index_pos: int):
    """Full detail + editable status fields for a shortlisted record."""
    sol_num  = str(row.get("Solicitation Number", "") or "").strip()
    title    = str(row.get("Title", "") or "")
    agency   = str(row.get("Agency", "") or "")
    sol_date = str(row.get("Solicitation Date", "") or "")
    due_date = str(row.get("Due Date", "") or "")
    opp_type = str(row.get("Opportunity Type", "") or "")
    set_aside= str(row.get("Normalized Set Aside", "") or "")
    link     = str(row.get("UiLink", "") or "").strip()

    st.markdown(f"### {title or '(No title)'}")
    st.caption(f"Solicitation #{sol_num}" if sol_num else "")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Agency:** {agency or '—'}")
        st.markdown(f"**Posted:** {sol_date or '—'}")
        st.markdown(f"**Due Date:** {due_date or '—'}")
    with c2:
        st.markdown(f"**Type:** {opp_type or '—'}")
        st.markdown(f"**Set Aside:** {set_aside or '—'}")
        st.markdown(f"**Sheet Row:** {sheet_row}")

    if link:
        st.link_button("🔗 Open on SAM.gov", link, use_container_width=True)

    st.divider()
    st.markdown("**Update Status**")

    cur_progress = str(row.get("Progress Report", "") or "")
    cur_award    = str(row.get("Award Status", "") or "")
    if "_user_names_cache" not in st.session_state:
        from auth import load_users as _lu
        st.session_state["_user_names_cache"] = [u["username"] for u in _lu()]
    _user_names  = st.session_state["_user_names_cache"]
    cur_assigned = str(row.get("Assigned To", "") or "")

    prog_opts = _PROGRESS_OPTIONS
    prog_idx  = prog_opts.index(cur_progress) if cur_progress in prog_opts else 0
    new_prog  = st.selectbox("Progress Report", prog_opts, index=prog_idx, key="_dlg_prog")

    award_opts= _AWARD_STATUS_OPTIONS
    award_idx = award_opts.index(cur_award) if cur_award in award_opts else 0
    new_award = st.selectbox("Award Status", award_opts, index=award_idx, key="_dlg_award")

    assign_opts = [""] + _user_names
    assign_idx  = assign_opts.index(cur_assigned) if cur_assigned in assign_opts else 0
    new_assigned= st.selectbox("Assigned To", assign_opts, index=assign_idx, key="_dlg_assigned")

    cur_notes  = str(row.get("Team Notes", "") or "")
    new_notes  = st.text_area("Team Notes", value=cur_notes, height=80, key="_dlg_notes")

    st.write("")
    if st.button("💾 Save Changes", type="primary", use_container_width=True, key="_dlg_save"):
        _now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _actor = st.session_state.get("username", "unknown")
        col_updates = {}
        if new_prog     != cur_progress: col_updates["Progress Report"] = new_prog
        if new_award    != cur_award:    col_updates["Award Status"]    = new_award
        if new_assigned != cur_assigned: col_updates["Assigned To"]     = new_assigned
        if new_notes    != cur_notes:    col_updates["Team Notes"]      = new_notes
        if col_updates:
            col_updates["Last Updated By"] = _actor
            col_updates["Last Updated At"] = _now

        # Optimistic session_state update
        if col_updates and "sol_data" in st.session_state:
            _df  = st.session_state["sol_data"].copy()
            _pos = orig_index_pos
            if _pos < len(_df):
                for _col, _val in col_updates.items():
                    if _col in _df.columns:
                        _df.at[_pos, _col] = _val
            st.session_state["sol_data"] = _df
            for _col, _orig_key in [
                ("Progress Report", "sol_original_progress"),
                ("Award Status",    "sol_original_award_status"),
                ("Assigned To",     "sol_original_assigned_to"),
            ]:
                if _col in _df.columns and st.session_state.get(_orig_key) is not None:
                    st.session_state[_orig_key] = _df[_col].copy().reset_index(drop=True)

        if not col_updates:
            st.info("No changes to save.")
        else:
            try:
                from google_connector import update_records_by_key, SHORTLISTED_TAB_NAME
                _record_key = sol_num or link
                with st.spinner("Saving changes…"):
                    _result = update_records_by_key(
                        {_record_key: col_updates}, SHORTLISTED_TAB_NAME
                    )
                if _result["updated"]:
                    _fetch_shortlisted.clear()
                    st.success("✅ Saved to the sheet.")
                else:
                    st.error("This solicitation was no longer present. Refresh and try again.")
            except Exception as exc:
                st.error(f"Save failed. Your values remain visible; please retry. {exc}")


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

    # Global search is deliberately above the filters so users can find a record
    # by any visible value (ID, title, agency, assignee, status, date, etc.).
    search_term = st.text_input(
        "Search all columns",
        placeholder="Type a solicitation number, title, agency, assignee, status…",
        key="shortlisted_global_search",
    ).strip()
    if search_term:
        searchable = df.fillna("").astype(str)
        matches = searchable.apply(
            lambda col: col.str.contains(search_term, case=False, regex=False, na=False)
        )
        matched_columns = [column for column in df.columns if matches[column].any()]
        df = df[matches.any(axis=1)].copy()
        total = len(df)
        st.caption(
            f"{total} match(es) · Found in: "
            + (", ".join(matched_columns) if matched_columns else "no columns")
        )

    # ── Filter pills — label includes live count ──
    # Compute parsed due dates once; reused for both the pill count and urgent filter.
    import datetime as _dt_mod
    _today        = _dt_mod.date.today()
    _due          = None
    _urgent_count = 0
    if "Due Date" in df.columns:
        try:
            from data_engine import force_date
            _due          = force_date(df["Due Date"].copy())
            _urgent_count = int((_due.notna() & (_due >= _today) & (_due < _today + _dt_mod.timedelta(days=10))).sum())
        except Exception:
            pass

    pill_options = ["All", f"🚨 Urgent  ({_urgent_count})"] + [
        f"{opt}  ({cat_counts.get(opt, 0)})" for opt in _PROGRESS_OPTIONS if opt
    ]
    active_pill = st.pills(
        "Filter",
        options=pill_options,
        selection_mode="single",
        default="All",
        key="sol_filter",
    ) or "All"

    # Determine Progress Report / Urgent filter
    _is_urgent_pill = active_pill.startswith("🚨 Urgent")
    active_filter   = "All" if _is_urgent_pill else (active_pill.split("  (")[0] if active_pill != "All" else "All")

    # Apply Progress Report / Urgent filter first (Set Aside pill counts are based on this subset)
    if _is_urgent_pill and _due is not None:
        _pr_df = df[_due.notna() & (_due >= _today) & (_due < _today + _dt_mod.timedelta(days=10))]
    elif active_filter != "All" and has_prog:
        _pr_df = df[df["Progress Report"] == active_filter]
    else:
        _pr_df = df

    # ── Set Aside filter pills ──────────────────────────────────────────────
    _has_sa   = "Normalized Set Aside" in df.columns
    active_sa = "All"
    if _has_sa:
        _sa_series = _pr_df["Normalized Set Aside"].dropna().astype(str).str.strip()
        _sa_counts = _sa_series[_sa_series.str.len() > 0].value_counts().to_dict()
        _sa_opts   = ["All"] + [
            f"{sa}  ({cnt})" for sa, cnt in sorted(_sa_counts.items(), key=lambda x: -x[1])
        ]
        _sa_pill  = st.pills(
            "Set Aside",
            options=_sa_opts,
            selection_mode="single",
            default="All",
            key="sol_sa_filter",
        ) or "All"
        active_sa = "All" if _sa_pill == "All" else _sa_pill.split("  (")[0]

    # Apply Set Aside filter on top of Progress Report filter
    if active_sa != "All" and _has_sa:
        _sa_mask   = _pr_df["Normalized Set Aside"].fillna("").astype(str).str.strip() == active_sa
        display_df = _pr_df[_sa_mask].reset_index(drop=False)
    else:
        display_df = _pr_df.reset_index(drop=False)

    # Combined key used for editor state and selection-reset detection.
    # Any change to either filter pill triggers a selection reset.
    _combined_filter = f"{active_filter}|{active_sa}"

    # Keep original df index so sheet row numbers stay correct
    orig_index = display_df["index"].tolist()
    display_df = display_df.drop(columns=["index"])

    _filter_parts = ([active_filter] if active_filter != "All" else []) + \
                    ([active_sa]     if active_sa     != "All" else [])
    st.caption(
        f"Showing {len(display_df)} of {total} solicitations"
        + (f" — {', '.join(_filter_parts)}" if _filter_parts else "")
    )
    st.caption("Change Progress Report or Assigned To — saves to the sheet automatically.")

    # Load registered users for the "Assigned To" dropdown.
    # Cached in session_state so the Gist network call only happens once per session,
    # not on every fragment rerun (every checkbox tick, filter change, etc.).
    if "_user_names_cache" not in st.session_state:
        from auth import load_users as _load_users_fn
        st.session_state["_user_names_cache"] = [u["username"] for u in _load_users_fn()]
    _user_names   = st.session_state["_user_names_cache"]
    _current_user = st.session_state.get("username", "")
    _has_assigned = "Assigned To" in display_df.columns

    # ── Delete / details toolbar (all users) ──────────
    _viewer_is_admin = st.session_state.get("role") == "admin"
    _marked_set      = set()
    _all_sheet_rows  = [i + 2 for i in orig_index]
    _editor_key      = f"sol_editor_{_combined_filter}"

    _marked_sheet_rows = st.session_state.get("_sol_delete_marked", [])
    _marked_set        = set(_marked_sheet_rows)
    _all_sheet_rows_set = set(_all_sheet_rows)
    _all_marked        = bool(_all_sheet_rows) and _marked_set == _all_sheet_rows_set

    # Reset selection whenever the filter pill changes (before any widget)
    if st.session_state.get("_sol_prev_filter") != _combined_filter:
        st.session_state["_sol_prev_filter"] = _combined_filter
        st.session_state.pop("_sol_delete_marked", None)
        st.session_state.pop(_editor_key, None)   # clear stale checked rows from prior visit
        st.session_state["_sol_chk_next"] = False
        _marked_sheet_rows = []
        _marked_set        = set()
        _all_marked        = False

    # Apply staged checkbox state — MUST happen before st.checkbox() renders
    if "_sol_chk_next" in st.session_state:
        st.session_state["select_all_chk"] = st.session_state.pop("_sol_chk_next")

    # Toolbar: [Select all] [Delete N] [Clear] [View Details]
    # Define columns first; render checkbox; run transitions; THEN render button.
    # _n_sel must be computed AFTER transitions so the count is correct on the
    # same run as the "Select All" click — not one rerun behind.
    _t1, _t2, _t3, _t4, _spacer = st.columns([2, 2, 1.5, 2, 2.5])

    with _t1:
        _select_all = st.checkbox("Select all", key="select_all_chk")

    # Select All / Deselect All transitions.
    # st.rerun() after each so the data_editor re-renders on the NEXT pass
    # with the correct pre-filled base — avoids stale visual state.
    if _select_all and not _all_marked:
        st.session_state["_sol_delete_marked"] = _all_sheet_rows
        st.session_state.pop(_editor_key, None)
        st.rerun()
    elif not _select_all and _all_marked:
        st.session_state.pop("_sol_delete_marked", None)
        st.session_state.pop(_editor_key, None)
        st.rerun()

    _n_sel = len(_marked_sheet_rows)

    # Resolve the visible selection to stable scraper keys. The connector
    # re-finds these keys in a fresh workbook before deleting anything.
    _selected_keys = []
    for _ii, _df_index in enumerate(orig_index):
        if _df_index + 2 in _marked_set:
            _selected_row = display_df.iloc[_ii]
            _selected_key = str(_selected_row.get("Solicitation Number", "") or "").strip()
            if not _selected_key:
                _selected_key = str(_selected_row.get("UiLink", "") or "").strip()
            if _selected_key:
                _selected_keys.append(_selected_key)

    def _execute_delete():
        try:
            with st.spinner(f"Deleting {_n_sel} rows…"):
                from google_connector import delete_records_by_key, SHORTLISTED_TAB_NAME
                _delete_result = delete_records_by_key(_selected_keys, SHORTLISTED_TAB_NAME)
            st.toast(f"Deleted {_delete_result['deleted']} rows.", icon="✅")
            st.session_state.pop("_sol_delete_marked", None)
            st.session_state.pop(_editor_key, None)
            st.session_state.pop("_sol_delete_confirm_conflicts", None)
            st.session_state["_sol_chk_next"] = False
            _fetch_shortlisted.clear()
            st.session_state.pop("sol_data", None)
            st.session_state.pop("sol_original_progress", None)
            st.session_state.pop("sol_original_assigned_to", None)
            st.session_state.pop("sol_original_award_status", None)
            st.rerun(scope="app")
        except Exception as _de:
            st.error(f"Delete failed: {_de}")

    with _t2:
        if _n_sel and st.button(f"🗑️ Delete {_n_sel}", type="primary", key="delete_top_btn"):
            # Check for rows claimed by other staff
            _conflicts = []
            if _has_assigned and "Assigned To" in display_df.columns:
                for _ii in range(len(display_df)):
                    _srow = orig_index[_ii] + 2
                    if _srow in _marked_set:
                        _assignee = str(display_df.iloc[_ii].get("Assigned To", "") or "").strip()
                        if _assignee and _assignee != _current_user:
                            _sol = str(display_df.iloc[_ii].get("Solicitation Number", ""))
                            _conflicts.append(f"{_sol} (claimed by {_assignee})")

            if _conflicts and not _viewer_is_admin:
                st.session_state["_sol_delete_block_msg"] = (
                    f"{len(_conflicts)} selected row(s) are claimed by other staff and cannot be deleted: "
                    + ", ".join(_conflicts[:3])
                    + ("…" if len(_conflicts) > 3 else "")
                )
                st.rerun()
            elif _conflicts:
                st.session_state["_sol_delete_confirm_conflicts"] = _conflicts
                st.rerun()
            else:
                _execute_delete()

    with _t3:
        if _n_sel and st.button("✕ Clear", key="clear_sel_btn"):
            st.session_state.pop("_sol_delete_marked", None)
            st.session_state.pop(_editor_key, None)
            st.session_state["_sol_chk_next"] = False
            st.rerun()

    with _t4:
        if _n_sel == 1 and st.button("👁 View Details", key="view_detail_btn", use_container_width=True):
            _detail_sheet_row = list(_marked_set)[0]
            _detail_df_idx    = _detail_sheet_row - 2
            if 0 <= _detail_df_idx < len(display_df):
                _detail_row = display_df.iloc[
                    next(i for i, idx in enumerate(orig_index) if idx == _detail_df_idx)
                ].to_dict()
                _shortlisted_detail_dialog(_detail_row, _detail_sheet_row, _detail_df_idx)

    # ── Conflict UI (shown below toolbar) ──────────────────────────────────
    _del_block  = st.session_state.pop("_sol_delete_block_msg", None)
    _del_conf   = st.session_state.get("_sol_delete_confirm_conflicts")

    if _del_block:
        st.error(f"🚫 {_del_block}")

    elif _del_conf:
        st.warning(
            f"⚠️ {len(_del_conf)} row(s) are claimed by other staff members. "
            "As admin you can override. Delete anyway?"
        )
        _oc1, _oc2, _ = st.columns([1.5, 1.5, 7])
        with _oc1:
            if st.button("Delete Anyway", type="primary", key="del_override_btn", use_container_width=True):
                _execute_delete()
        with _oc2:
            if st.button("Cancel", key="del_cancel_btn", use_container_width=True):
                st.session_state.pop("_sol_delete_confirm_conflicts", None)
                st.rerun()

    _cols = display_df.columns.tolist()
    col_cfg = {}

    # Delete-selection column — pre-filled from current marked set (all users)
    display_df = display_df.copy()
    display_df["_delete"] = [(orig_index[i] + 2) in _marked_set for i in range(len(display_df))]
    col_cfg["_delete"] = st.column_config.CheckboxColumn("🗑️", width=38)

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
    if _has_assigned:
        col_cfg["Assigned To"] = st.column_config.SelectboxColumn(
            "Assigned To",
            options=[""] + _user_names,
            required=False,
            width=130,
        )
    _has_award = "Award Status" in _cols
    if _has_award:
        col_cfg["Award Status"] = st.column_config.SelectboxColumn(
            "Award Status",
            options=_AWARD_STATUS_OPTIONS,
            required=False,
            width=140,
        )

    _preferred_order = [
        "_delete",
        "Solicitation Number", "Title", "Agency", "Solicitation Date",
        "Due Date", "Opportunity Type", "Normalized Set Aside",
        "Progress Report", "Award Status", "Assigned To", "UiLink",
    ]
    all_cols     = display_df.columns.tolist()
    column_order = [c for c in _preferred_order if c in all_cols]
    editable     = (
        ["_delete"] +
        (["Progress Report"] if "Progress Report" in _cols else []) +
        (["Award Status"] if _has_award else []) +
        (["Assigned To"] if _has_assigned else [])
    )
    disabled     = [c for c in all_cols if c not in editable]

    edited_df = st.data_editor(
        display_df,
        column_config=col_cfg,
        column_order=column_order,
        disabled=disabled,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=_editor_key,
        height=560,
    )

    # ── Sync row checkboxes → session_state ──────────────────────────────────────
    # edited_df["_delete"] is always the authoritative current state.
    # When it differs from what we stored last render, persist the new selection
    # and do ONE fragment rerun so the delete button count at the top updates.
    if "_delete" in edited_df.columns:
        _newly_marked     = [orig_index[i] + 2 for i, v in enumerate(edited_df["_delete"]) if v]
        _prev_marked      = st.session_state.get("_sol_delete_marked", [])
        if set(_newly_marked) != set(_prev_marked):
            st.session_state["_sol_delete_marked"] = _newly_marked
            _newly_all = bool(_all_sheet_rows) and set(_newly_marked) == _all_sheet_rows_set
            st.session_state["_sol_chk_next"] = _newly_all
            st.rerun()   # fragment rerun — brings top count in sync

    # ── Auto-save on change ───────────────────
    original_prog = st.session_state.get("sol_original_progress")
    if original_prog is not None and "Progress Report" in edited_df.columns:
        # Fast-path: skip O(N) scan if edited_rows has no Progress Report edits
        _edited_rows_map = st.session_state.get(_editor_key, {}).get("edited_rows", {})
        _has_prog_edit   = any("Progress Report" in v for v in _edited_rows_map.values())
        if not _has_prog_edit:
            original_prog = None   # nothing changed — skip the block below

    if original_prog is not None and "Progress Report" in edited_df.columns:
        updates = {}
        for pos, (df_idx, new_val) in enumerate(
            zip(orig_index, edited_df["Progress Report"])
        ):
            old_val = original_prog.iloc[df_idx] if df_idx < len(original_prog) else ""
            if str(new_val or "") != str(old_val or ""):
                updates[df_idx + 2] = str(new_val or "")

        if updates:
            # Optimistic update — only write changed rows (same pattern as Assigned To)
            full_df = st.session_state["sol_data"].copy()
            for _sheet_row, _new_val in updates.items():
                full_df.at[int(_sheet_row) - 2, "Progress Report"] = _new_val
            st.session_state["sol_data"] = full_df
            st.session_state["sol_original_progress"] = (
                full_df["Progress Report"].copy().reset_index(drop=True)
            )

            _save_result: dict = {}
            _actor = st.session_state.get("username", "unknown")
            _keyed_progress = {}
            for _sheet_row, _new_val in updates.items():
                _row = full_df.iloc[int(_sheet_row) - 2]
                _key = str(_row.get("Solicitation Number", "") or "").strip() or str(
                    _row.get("UiLink", "") or ""
                ).strip()
                if _key:
                    _keyed_progress[_key] = {"Progress Report": _new_val}

            # Capture changed statuses for activity logging
            _changed = []
            full_df_snap = st.session_state["sol_data"]
            for df_idx, new_val in updates.items():
                row_pos = df_idx - 2  # sheet row → df index
                sol_num = full_df_snap.iloc[row_pos].get("Solicitation Number", "") if row_pos < len(full_df_snap) else ""
                old_val = str(original_prog.iloc[row_pos] if row_pos < len(original_prog) else "")
                _changed.append({"solicitation": str(sol_num), "old_status": old_val, "new_status": str(new_val)})

            def _bg_save(u=_keyed_progress, r=_save_result, actor=_actor, changed=_changed):
                try:
                    from google_connector import update_records_by_key, SHORTLISTED_TAB_NAME
                    _saved = update_records_by_key(u, SHORTLISTED_TAB_NAME)
                    r["count"] = _saved["updated"]
                    r["missing"] = _saved["missing"]
                    r["ok"] = True
                    # Log each status change
                    from agent_state import log_user_activity
                    for ch in changed:
                        log_user_activity(actor, "progress_update", ch)
                except Exception as exc:
                    r["error"] = str(exc)

            _t = threading.Thread(target=_bg_save, daemon=True)
            _t.start()
            st.session_state["_sol_save"] = (_t, _save_result)
            log_event("update_progress", "pending", f"{len(updates)} rows queued")
            st.toast("💾 Saving…")

    # ── Auto-save Assigned To on change ──────────────────────────────────────
    original_assigned = st.session_state.get("sol_original_assigned_to")
    if original_assigned is not None and _has_assigned and "Assigned To" in edited_df.columns:
        _edited_rows_map2 = st.session_state.get(_editor_key, {}).get("edited_rows", {})
        if not any("Assigned To" in v for v in _edited_rows_map2.values()):
            original_assigned = None

    if original_assigned is not None and _has_assigned and "Assigned To" in edited_df.columns:
        _assigned_updates = {}
        for _df_idx, _new_val in zip(orig_index, edited_df["Assigned To"]):
            _old_val = original_assigned.iloc[_df_idx] if _df_idx < len(original_assigned) else ""
            if str(_new_val or "") != str(_old_val or ""):
                _assigned_updates[_df_idx + 2] = str(_new_val or "")

        if _assigned_updates:
            full_df = st.session_state["sol_data"].copy()
            # Only touch the rows that actually changed — writing all visible rows
            # would overwrite legitimate assignments outside the current filter.
            for _sheet_row, _new_val in _assigned_updates.items():
                full_df.at[int(_sheet_row) - 2, "Assigned To"] = _new_val
            st.session_state["sol_data"] = full_df
            st.session_state["sol_original_assigned_to"] = (
                full_df["Assigned To"].copy().reset_index(drop=True)
            )

            _assigned_result: dict = {}
            _actor2 = st.session_state.get("username", "unknown")
            _keyed_assigned = {}
            for _sheet_row, _new_val in _assigned_updates.items():
                _row = full_df.iloc[int(_sheet_row) - 2]
                _key = str(_row.get("Solicitation Number", "") or "").strip() or str(
                    _row.get("UiLink", "") or ""
                ).strip()
                if _key:
                    _keyed_assigned[_key] = {"Assigned To": _new_val}

            def _bg_save_assigned(u=_keyed_assigned, r=_assigned_result, actor=_actor2):
                try:
                    from google_connector import update_records_by_key, SHORTLISTED_TAB_NAME
                    _saved = update_records_by_key(u, SHORTLISTED_TAB_NAME)
                    r["count"] = _saved["updated"]
                    r["missing"] = _saved["missing"]
                    r["ok"] = True
                    from agent_state import log_user_activity
                    log_user_activity(actor, "assigned_to_update", {"rows": list(u.keys())})
                except Exception as exc:
                    r["error"] = str(exc)

            _ta = threading.Thread(target=_bg_save_assigned, daemon=True)
            _ta.start()
            st.session_state["_sol_assigned_save"] = (_ta, _assigned_result)
            st.toast("💾 Saving assignment…")

    # ── Auto-save Award Status on change ─────────────────────────────────────
    original_award = st.session_state.get("sol_original_award_status")
    if original_award is not None and _has_award and "Award Status" in edited_df.columns:
        _edited_rows_map3 = st.session_state.get(_editor_key, {}).get("edited_rows", {})
        if not any("Award Status" in v for v in _edited_rows_map3.values()):
            original_award = None

    if original_award is not None and _has_award and "Award Status" in edited_df.columns:
        _award_updates = {}
        for _df_idx, _new_val in zip(orig_index, edited_df["Award Status"]):
            _old_val = original_award.iloc[_df_idx] if _df_idx < len(original_award) else ""
            if str(_new_val or "") != str(_old_val or ""):
                _award_updates[_df_idx + 2] = str(_new_val or "")

        if _award_updates:
            full_df = st.session_state["sol_data"].copy()
            for _sheet_row, _new_val in _award_updates.items():
                full_df.at[int(_sheet_row) - 2, "Award Status"] = _new_val
            st.session_state["sol_data"] = full_df
            st.session_state["sol_original_award_status"] = (
                full_df["Award Status"].copy().reset_index(drop=True)
            )

            _award_result: dict = {}
            _actor3 = st.session_state.get("username", "unknown")
            _keyed_award = {}
            for _sheet_row, _new_val in _award_updates.items():
                _row = full_df.iloc[int(_sheet_row) - 2]
                _key = str(_row.get("Solicitation Number", "") or "").strip() or str(
                    _row.get("UiLink", "") or ""
                ).strip()
                if _key:
                    _keyed_award[_key] = {"Award Status": _new_val}

            def _bg_save_award(u=_keyed_award, r=_award_result, actor=_actor3):
                try:
                    from google_connector import update_records_by_key, SHORTLISTED_TAB_NAME
                    _saved = update_records_by_key(u, SHORTLISTED_TAB_NAME)
                    r["count"] = _saved["updated"]
                    r["missing"] = _saved["missing"]
                    r["ok"] = True
                    from agent_state import log_user_activity
                    log_user_activity(actor, "award_status_update", {"rows": list(u.keys())})
                except Exception as exc:
                    r["error"] = str(exc)

            _tw = threading.Thread(target=_bg_save_award, daemon=True)
            _tw.start()
            st.session_state["_sol_award_save"] = (_tw, _award_result)
            st.toast("💾 Saving award status…")


def show_shortlisted():
    _workspace_header(
        "ACTIVE WORKSPACE",
        "⭐ Shortlisted Solicitations",
        "The shared processing workspace for ownership, progress, deadlines, and award outcomes.",
        ["Find a record", "Assign an owner", "Update progress", "Track outcome"],
    )
    _workspace_guide("shortlisted")

    # Report any completed background saves from the previous interaction
    for _save_key, _label in [("_sol_save", "status"), ("_sol_assigned_save", "assignment"), ("_sol_award_save", "award status")]:
        _pending = st.session_state.get(_save_key)
        if _pending:
            _t, _r = _pending
            if not _t.is_alive():
                st.session_state.pop(_save_key, None)
                if _r.get("ok"):
                    st.toast(f"✅ {_r['count']} {_label}(s) saved to sheet", icon="✅")
                elif _r.get("error"):
                    st.toast(f"❌ Save failed: {_r['error']}", icon="❌")

    col_back, col_find, col_refresh, col_status = st.columns([1.5, 2.5, 2, 4])
    with col_back:
        if st.button("← Home"):
            goto("landing")
    with col_find:
        if st.button("🔎 Find Opportunities", use_container_width=True):
            goto("solicitations")
    with col_refresh:
        if st.button("🔄 Refresh from Sheet"):
            _fetch_shortlisted.clear()
            st.session_state.pop("sol_data", None)
            st.session_state.pop("sol_original_progress", None)
            st.session_state.pop("sol_original_assigned_to", None)
            st.session_state.pop("sol_original_award_status", None)
            st.session_state["sol_status"] = "loading"
            st.rerun()

    # Refresh session data after one minute on the next interaction so another
    # teammate's changes do not remain hidden for the whole login session.
    if (
        "sol_data" in st.session_state
        and datetime.datetime.now().timestamp() - st.session_state.get("sol_loaded_at", 0) > 60
    ):
        st.session_state.pop("sol_data", None)
        _fetch_shortlisted.clear()

    # ── Load data (serve from memory cache, fetch from Drive only on cold start) ──
    sheet_status = st.session_state.get("sol_status", "idle")
    status_placeholder = col_status.empty()

    if "sol_data" not in st.session_state:
        status_placeholder.info("⏳ Loading sheet…")
        try:
            df = _fetch_shortlisted()

            st.session_state["sol_data"] = df
            st.session_state["sol_loaded_at"] = datetime.datetime.now().timestamp()
            st.session_state["sol_original_progress"] = (
                df["Progress Report"].copy().reset_index(drop=True)
                if "Progress Report" in df.columns else None
            )
            st.session_state["sol_original_assigned_to"] = (
                df["Assigned To"].copy().reset_index(drop=True)
                if "Assigned To" in df.columns else None
            )
            st.session_state["sol_original_award_status"] = (
                df["Award Status"].copy().reset_index(drop=True)
                if "Award Status" in df.columns else None
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

    # Back-fill columns for sessions where sol_data was cached before they existed.
    _df_dirty = False
    if "Assigned To" not in df.columns:
        df = df.copy(); _df_dirty = True
        df["Assigned To"] = ""
        if st.session_state.get("sol_original_assigned_to") is None:
            st.session_state["sol_original_assigned_to"] = df["Assigned To"].copy().reset_index(drop=True)
    if "Award Status" not in df.columns:
        if not _df_dirty:
            df = df.copy(); _df_dirty = True
        df["Award Status"] = ""
        if st.session_state.get("sol_original_award_status") is None:
            st.session_state["sol_original_award_status"] = df["Award Status"].copy().reset_index(drop=True)
    if _df_dirty:
        st.session_state["sol_data"] = df

    if df.empty:
        st.info("No shortlisted solicitations yet. Select qualified opportunities from Find Opportunities.")
        return

    _sol_filter_and_table(df)

    with st.expander("🚨 Urgent shortlisted solicitations", expanded=False):
        # Refresh Urgent sheet tab + clear expired in background when user opens it
        if st.button("🔄 Refresh Urgent", key="refresh_urgent"):
            def _bg_urgent():
                try:
                    from google_connector import refresh_urgent_tab
                    refresh_urgent_tab()
                    _fetch_urgent.clear()
                except Exception:
                    pass
            threading.Thread(target=_bg_urgent, daemon=True).start()
            _fetch_urgent.clear()
            st.toast("🔄 Urgent tab refreshed")

        try:
            df_urgent = _fetch_urgent()
        except Exception as e:
            st.error(f"Could not load Urgent tab: {e}")
            df_urgent = None

        if df_urgent is None or df_urgent.empty:
            st.info("No urgent solicitations right now — all due dates are 10+ days away or the tab hasn't been populated yet. Run the pipeline or click Refresh Urgent above.")
        else:
            st.caption(f"**{len(df_urgent)}** solicitation(s) due within the next 10 days.")
            st.dataframe(df_urgent, use_container_width=True, hide_index=True)


def show_solicitations():
    """Intake workspace: find and move qualified opportunities into active work."""
    _workspace_header(
        "OPPORTUNITY INTAKE",
        "🔎 Find Opportunities",
        "Search the incoming pool, review qualified opportunities, and move the right solicitations into team processing.",
        ["Search or filter", "Review details", "Select qualified rows", "Shortlist"],
    )
    _workspace_guide("opportunities")

    try:
        shortlisted_count = len(_fetch_shortlisted())
    except Exception:
        shortlisted_count = 0

    c_home, c_short, c_refresh, c_status = st.columns([1.3, 2.8, 2, 3.9])
    with c_home:
        if st.button("← Home", key="opp_home"):
            goto("landing")
    with c_short:
        if st.button(
            f"⭐ View Shortlisted ({shortlisted_count}) →",
            key="opp_view_shortlisted",
            use_container_width=True,
            type="primary",
        ):
            goto("shortlisted")
    with c_refresh:
        if st.button("🔄 Refresh", key="opp_refresh", use_container_width=True):
            _fetch_solicitations.clear()
            st.session_state.pop("opportunities_data", None)
            st.rerun()

    if (
        "opportunities_data" in st.session_state
        and datetime.datetime.now().timestamp() - st.session_state.get("opportunities_loaded_at", 0) > 60
    ):
        st.session_state.pop("opportunities_data", None)
        _fetch_solicitations.clear()

    if "opportunities_data" not in st.session_state:
        try:
            with c_status:
                st.caption("Loading the latest intake sheet…")
            df = _fetch_solicitations()
            # Intake cleanup remains limited to unselected, expired candidates.
            df, expired_rows = _purge_expired(df)
            if expired_rows:
                from google_connector import delete_expired_rows
                delete_expired_rows(expired_rows)
                _fetch_solicitations.clear()
            st.session_state["opportunities_data"] = df
            st.session_state["opportunities_loaded_at"] = datetime.datetime.now().timestamp()
        except Exception as exc:
            st.error(f"Could not load Opportunities: {exc}")
            return
    df = st.session_state["opportunities_data"].copy()

    search = st.text_input(
        "Search all columns",
        placeholder="Type an ID, title, agency, set-aside, date, or any other value…",
        key="opportunities_global_search",
    ).strip()
    matched_columns = []
    if search:
        searchable = df.fillna("").astype(str)
        match_cells = searchable.apply(
            lambda col: col.str.contains(search, case=False, regex=False, na=False)
        )
        matched_columns = [column for column in df.columns if match_cells[column].any()]
        df = df[match_cells.any(axis=1)].copy()

    filter_col, urgent_col, result_col = st.columns([3, 2, 5])
    with filter_col:
        set_asides = ["All"]
        if "Normalized Set Aside" in df.columns:
            set_asides += sorted(
                value for value in df["Normalized Set Aside"].fillna("").astype(str).unique()
                if value.strip()
            )
        selected_set_aside = st.selectbox("Set Aside", set_asides, key="opp_set_aside")
    with urgent_col:
        urgent_only = st.toggle("Due within 10 days", key="opp_urgent_only")

    if selected_set_aside != "All" and "Normalized Set Aside" in df.columns:
        df = df[df["Normalized Set Aside"].fillna("").astype(str) == selected_set_aside]
    if urgent_only and "Due Date" in df.columns:
        today = datetime.date.today()
        due = __import__("pandas").to_datetime(df["Due Date"], errors="coerce").dt.date
        df = df[due.notna() & (due >= today) & (due < today + datetime.timedelta(days=10))]

    with result_col:
        st.write("")
        detail = f"Showing {len(df)} of {len(st.session_state['opportunities_data'])} opportunities"
        if search:
            detail += " · matched: " + (", ".join(matched_columns) if matched_columns else "none")
        st.caption(detail)

    if df.empty:
        st.info("No opportunities match the current search and filters.")
        return

    table = df.copy()
    table.insert(0, "_shortlist", False)
    preferred = [
        "_shortlist", "Solicitation Number", "Title", "Agency", "Solicitation Date",
        "Due Date", "Opportunity Type", "Normalized Set Aside", "UiLink",
    ]
    column_order = [column for column in preferred if column in table.columns]
    config = {
        "_shortlist": st.column_config.CheckboxColumn("Select", width="small"),
        "UiLink": st.column_config.LinkColumn("SAM.gov", display_text="Open", width="small"),
    }
    edited = st.data_editor(
        table,
        column_config=config,
        column_order=column_order,
        disabled=[column for column in table.columns if column != "_shortlist"],
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        height=600,
        key="opportunities_selector",
    )
    chosen = edited[edited["_shortlist"]]
    chosen_count = len(chosen)
    action, review_col, hint = st.columns([3, 2, 5])
    with action:
        if st.button(
            f"⭐ Shortlist selected ({chosen_count})",
            type="primary",
            disabled=chosen_count == 0,
            use_container_width=True,
            key="move_to_shortlisted",
        ):
            keys = []
            for _, row in chosen.iterrows():
                key = str(row.get("Solicitation Number", "") or "").strip()
                if not key:
                    key = str(row.get("UiLink", "") or "").strip()
                if key:
                    keys.append(key)
            try:
                with st.spinner("Moving selected solicitations safely…"):
                    from google_connector import shortlist_solicitations
                    result = shortlist_solicitations(keys, st.session_state.get("username", "unknown"))
                try:
                    from agent_state import log_user_activity
                    log_user_activity(
                        st.session_state.get("username", "unknown"),
                        "shortlist",
                        {"count": result["moved"], "solicitations": keys},
                    )
                except Exception:
                    pass
                _fetch_solicitations.clear()
                _fetch_shortlisted.clear()
                _fetch_urgent.clear()
                st.session_state.pop("opportunities_data", None)
                st.session_state.pop("sol_data", None)
                st.success(f"Moved {result['moved']} solicitation(s) to Shortlisted.")
                st.session_state.page = "shortlisted"
                st.query_params["page"] = "shortlisted"
                st.rerun()
            except Exception as exc:
                st.error(f"Shortlisting failed; no partial move was saved. {exc}")
    with review_col:
        if chosen_count == 1 and st.button("👁 Review Details", use_container_width=True,
                                            key="opp_review_btn"):
            _row = chosen.iloc[0].to_dict()
            _key = str(_row.get("Solicitation Number") or _row.get("UiLink") or "").strip()
            _opp_sheet_row = int(chosen.index[0]) + 2
            _opportunity_detail_dialog(_row, [_key] if _key else [], sheet_row=_opp_sheet_row)
    with hint:
        st.caption("Check one row and click Review Details to see the full record, or select multiple and Shortlist them.")


@st.fragment(run_every=1)
def _countdown_fragment():
    import datetime as _dt
    now = _dt.datetime.utcnow()
    next_h = (now.hour // 4 + 1) * 4
    if next_h >= 24:
        next_dt = (now + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        next_dt = now.replace(hour=next_h, minute=0, second=0, microsecond=0)
    total_secs = max(0, int((next_dt - now).total_seconds()))
    hh, rem = divmod(total_secs, 3600)
    mm, ss = divmod(rem, 60)
    next_label = f"{next_h % 24:02d}:00 UTC"
    ct = f"{hh:02d}:{mm:02d}:{ss:02d}"
    st.markdown(
        f"""<div style="background:rgba(30,144,255,0.08);border:1px solid rgba(30,144,255,0.25);
border-radius:12px;padding:.85rem 1.4rem;display:flex;align-items:center;gap:2.5rem;flex-wrap:wrap;">
  <div><div style="font-size:.7rem;color:rgba(180,180,180,.8);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.2rem;">Next Auto-Run</div>
       <div style="font-size:.9rem;color:rgba(200,200,200,.9);">{next_label}</div></div>
  <div><div style="font-size:.7rem;color:rgba(180,180,180,.8);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.2rem;">Countdown</div>
       <div style="font-size:1.7rem;font-weight:700;font-family:monospace;color:#1E90FF;letter-spacing:.05em;">{ct}</div></div>
</div>""",
        unsafe_allow_html=True,
    )


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
                Scans for new opportunity files and updates the solicitations sheet automatically
                every&nbsp;<strong>4&nbsp;hours</strong>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Operations"):
        goto("operations")

    # ── Countdown to next auto-run ────────────────────────────
    _countdown_fragment()

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
        from agent_state import is_pipeline_running, set_pipeline_running, clear_pipeline_running
        _is_admin = st.session_state.get("role") == "admin"
        _actor    = st.session_state.get("username", "unknown")

        # ── Pipeline lock banner ──────────────────────────────
        _locked, _lock_user, _lock_ts = is_pipeline_running()
        if _locked:
            try:
                _lock_ts_fmt = datetime.fromisoformat(_lock_ts).strftime("%H:%M UTC")
            except Exception:
                _lock_ts_fmt = _lock_ts or "?"
            st.warning(
                f"⏳ **Pipeline is currently running** — started by **{_lock_user}** at {_lock_ts_fmt}. "
                "Please wait for it to finish before starting another run."
            )

        # ── Admin-only controls ───────────────────────────────
        if _is_admin:
            col_btn, col_reset, col_dv, col_sol = st.columns([3, 2, 2, 2])
            with col_btn:
                run_now = st.button(
                    "▶ Run Latest Update", type="primary",
                    use_container_width=True, disabled=_locked
                )
            with col_reset:
                reset_btn = st.button(
                    "🔄 Reset Seen Files", type="secondary", use_container_width=True,
                    help="Clears the processed-file memory. The next run will re-process ALL files.",
                    disabled=_locked,
                )
            with col_dv:
                apply_dv = st.button(
                    "Apply Dropdown to Sheet", type="secondary", use_container_width=True,
                    help="Re-applies the Progress Report dropdown validation to the master sheet."
                )
            with col_sol:
                if st.button("📋 View Solicitations", type="secondary", use_container_width=True):
                    goto("solicitations")
        else:
            run_now   = False
            reset_btn = False
            apply_dv  = False
            if st.button("📋 View Solicitations", type="primary", use_container_width=True):
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

            set_pipeline_running(_actor)
            with st.spinner("Running pipeline…"):
                try:
                    summary = run_pipeline(progress_callback=_cb)
                    progress_box.empty()

                    record_run("manual", summary)

                    if summary["errors"]:
                        result_box.error(
                            "Pipeline encountered errors:\n" + "\n".join(summary["errors"])
                        )
                    elif summary["files_processed"] == 0:
                        result_box.info(f"ℹ️ {summary.get('message', 'No new files to process.')}")
                        st.session_state["sol_just_updated"] = True
                    else:
                        names = ", ".join(f["name"] for f in summary.get("processed_files", []))
                        rows  = summary["total_rows_added"]
                        result_box.success(f"✅ **{rows} rows** appended from: {names}")
                        _fetch_solicitations.clear()
                        _fetch_urgent.clear()
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
                finally:
                    clear_pipeline_running()

        # View solicitations shortcut after a successful run
        if st.session_state.get("sol_just_updated"):
            st.success("✅ Pipeline complete — solicitations have been updated.")
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
        # Always pull fresh state from Gist so GitHub Actions runs are visible
        _sync_col, _ = st.columns([1, 4])
        with _sync_col:
            if st.button("🔄 Sync State", help="Pull latest run data from the cloud"):
                try:
                    from agent_state import sync_from_gist
                    sync_from_gist()
                    s = get_summary()
                    st.toast("✅ State synced")
                except Exception as _se:
                    st.warning(f"Sync failed: {_se}")

        run_log = s.get("run_log", [])

        if not run_log:
            st.info("No run history yet — click Sync State to pull the latest data, or trigger a run.")
        else:
            table_rows = []
            for entry in run_log:
                ts = entry.get("timestamp", "")
                try:
                    ts_fmt = datetime.fromisoformat(ts).strftime("%b %d, %Y  %H:%M UTC")
                except Exception:
                    ts_fmt = ts

                status_label = {
                    "success":      "✅ Success",
                    "error":        "❌ Error",
                    "no_new_files": "ℹ️ No New Files",
                }.get(entry.get("status", ""), "—")

                table_rows.append({
                    "Date / Time":      ts_fmt,
                    "Triggered By":     entry.get("triggered_by", "?").capitalize(),
                    "Status":           status_label,
                    "Files Processed":  entry.get("files_processed", 0),
                    "Rows Added":       entry.get("rows_added", 0),
                })

            st.dataframe(
                pd.DataFrame(table_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Date / Time":     st.column_config.TextColumn("Date / Time",    width="medium"),
                    "Triggered By":    st.column_config.TextColumn("Triggered By",   width="small"),
                    "Status":          st.column_config.TextColumn("Status",         width="medium"),
                    "Files Processed": st.column_config.NumberColumn("Files",        width="small"),
                    "Rows Added":      st.column_config.NumberColumn("Rows Added",   width="small"),
                },
            )

            col_dl, _ = st.columns([2, 5])
            with col_dl:
                csv_bytes = pd.DataFrame(table_rows).to_csv(index=False).encode()
                st.download_button("⬇ Download Run Log CSV", csv_bytes, "run_history.csv", mime="text/csv")

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

    # ── Tab 5: Schedule ───────────────────────────────────────
    with tab_cfg:
        st.subheader("Automatic Schedule")
        st.write("The agent runs automatically every **4 hours**.")
        _countdown_fragment()
        st.write("")
        if st.button("📋 View Solicitations", key="cfg_view_sol"):
            goto("solicitations")

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
    _back_col, _doc_col = st.columns([3, 2])
    with _back_col:
        if st.button("← Back to Operations"):
            goto("operations")
    with _doc_col:
        try:
            _guide_text = open("SYSTEM_GUIDE.md", "r", encoding="utf-8").read()
            st.download_button(
                "📄 Download System Guide",
                data=_guide_text.encode("utf-8"),
                file_name="Almor_Survey_Agent_System_Guide.md",
                mime="text/markdown",
                use_container_width=True,
            )
        except Exception:
            pass

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
                        st.session_state.pop("_user_names_cache", None)  # refresh dropdown
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
            st.caption(f"{len(users)} registered user(s)")
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
                    _is_self = uname == st.session_state.get("username")
                    if _is_self:
                        st.info("This is your own account. Role and delete actions are disabled for your own account.")
                    else:
                        c1, c2, c3 = st.columns([2, 2, 2])
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
                            if st.button("Save Role", key=f"update_{i}", use_container_width=True):
                                success, message = update_user_role(uname, new_role)
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
                        with c3:
                            st.write("")
                            st.write("")
                            _confirm_key = f"confirm_del_user_{i}"
                            if st.session_state.get(_confirm_key):
                                st.warning(f"Remove **{uname}**?")
                                _dc1, _dc2 = st.columns(2)
                                with _dc1:
                                    if st.button("Yes, remove", key=f"del_yes_{i}", type="primary", use_container_width=True):
                                        st.session_state.pop(_confirm_key, None)
                                        ok, msg = delete_user(uname)
                                        if ok:
                                            st.session_state.pop("_user_names_cache", None)  # refresh dropdown
                                            st.success(msg)
                                            st.rerun()
                                        else:
                                            st.error(msg)
                                with _dc2:
                                    if st.button("Cancel", key=f"del_no_{i}", use_container_width=True):
                                        st.session_state.pop(_confirm_key, None)
                                        st.rerun()
                            else:
                                if st.button("🗑 Remove Access", key=f"del_btn_{i}", use_container_width=True):
                                    st.session_state[_confirm_key] = True
                                    st.rerun()

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
# STAFF PAGE  (admin only)
# -------------------------------------------------
def show_staff():
    import pandas as pd
    from datetime import datetime as dt, date, timedelta
    from agent_state import get_user_activity_log
    from auth import load_users

    if st.session_state.get("role") != "admin":
        st.error("Access denied.")
        return

    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown(
        "<div class='app-card'><div class='app-title'>Staff</div>"
        "<div class='app-subtitle'>User activity — logins, session time, and progress report updates.</div></div>",
        unsafe_allow_html=True,
    )
    if st.button("← Back to Operations"):
        goto("operations")

    # ── Date range filter ─────────────────────────────────────
    st.write("")
    fc1, fc2 = st.columns(2)
    with fc1:
        from_date = st.date_input("From", value=date.today() - timedelta(days=30), key="staff_from")
    with fc2:
        to_date = st.date_input("To", value=date.today(), key="staff_to")

    from_dt = dt.combine(from_date, dt.min.time())
    to_dt   = dt.combine(to_date,   dt.max.time())

    all_log = get_user_activity_log(from_dt=from_dt, to_dt=to_dt)
    users   = load_users()
    usernames = [u["username"] for u in users]

    # Full status name → short display label
    _STATUS_LABELS = {
        "Bid Submitted":          "Submitted",
        "Bid InProgress":         "In Progress",
        "Sub Contractor Inquiry": "Sub Inquiry",
        "Bid Past Due Date":      "Past Due",
        "Bid Quote Requested":    "Quote Req.",
    }
    _STATUSES = list(_STATUS_LABELS.keys())

    # ── Summary table ─────────────────────────────────────────
    st.divider()
    st.subheader("Progress Update Counts by User")

    rows = []
    for uname in usernames:
        u_log = [e for e in all_log if e.get("username") == uname]

        logins   = [e for e in u_log if e.get("action") == "login"]
        logouts  = [e for e in u_log if e.get("action") == "logout"]
        updates  = [e for e in u_log if e.get("action") == "progress_update"]

        # Estimate hours: pair each login with the next logout (or cap at 2h)
        login_times  = sorted([e["timestamp"] for e in logins])
        logout_times = sorted([e["timestamp"] for e in logouts])
        total_mins   = 0
        li = 0
        for lt in logout_times:
            while li < len(login_times) and login_times[li] < lt:
                li += 1
            if li > 0:
                try:
                    gap = (dt.fromisoformat(lt) - dt.fromisoformat(login_times[li - 1])).total_seconds() / 60
                    total_mins += min(gap, 120)
                except Exception:
                    pass
        total_mins += max(0, len(logins) - len(logouts)) * 15

        row = {
            "User":          uname,
            "Logins":        len(logins),
            "Active Hours":  f"{total_mins / 60:.1f}h",
            "Total Updates": len(updates),
        }
        for full, short in _STATUS_LABELS.items():
            row[short] = sum(1 for e in updates if e.get("new_status") == full)
        rows.append(row)

    if rows:
        df_summary = pd.DataFrame(rows)

        # Totals row
        totals = {"User": "TOTAL", "Logins": "", "Active Hours": ""}
        totals["Total Updates"] = df_summary["Total Updates"].sum()
        for short in _STATUS_LABELS.values():
            totals[short] = df_summary[short].sum()
        df_summary = pd.concat(
            [df_summary, pd.DataFrame([totals])], ignore_index=True
        )

        st.dataframe(
            df_summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "User":          st.column_config.TextColumn("User",         width="small"),
                "Logins":        st.column_config.TextColumn("Logins",       width="small"),
                "Active Hours":  st.column_config.TextColumn("Active Hrs",   width="small"),
                "Total Updates": st.column_config.NumberColumn("Total",      width="small"),
                "Submitted":     st.column_config.NumberColumn("Submitted",  width="small"),
                "In Progress":   st.column_config.NumberColumn("In Progress",width="small"),
                "Sub Inquiry":   st.column_config.NumberColumn("Sub Inquiry",width="small"),
                "Past Due":      st.column_config.NumberColumn("Past Due",   width="small"),
                "Quote Req.":    st.column_config.NumberColumn("Quote Req.", width="small"),
            },
        )

        # Download
        csv_staff = df_summary.to_csv(index=False).encode()
        st.download_button("⬇ Download Staff Summary CSV", csv_staff,
                           "staff_summary.csv", mime="text/csv")
    else:
        st.info("No activity recorded in the selected date range.")

    # ── Detailed activity log ─────────────────────────────────
    st.divider()
    st.subheader("Detailed Activity Log")

    user_filter = st.selectbox("Filter by user", ["All"] + usernames, key="staff_user_filter")
    action_filter = st.selectbox(
        "Filter by action", ["All", "login", "logout", "progress_update"],
        key="staff_action_filter"
    )

    filtered = all_log
    if user_filter != "All":
        filtered = [e for e in filtered if e.get("username") == user_filter]
    if action_filter != "All":
        filtered = [e for e in filtered if e.get("action") == action_filter]

    if filtered:
        df_log = pd.DataFrame(filtered)
        # Friendly timestamp
        if "timestamp" in df_log.columns:
            df_log["timestamp"] = pd.to_datetime(df_log["timestamp"]).dt.strftime("%b %d, %Y  %H:%M UTC")
        st.dataframe(df_log, use_container_width=True, hide_index=True)
        st.caption(f"{len(filtered)} event(s)")
    else:
        st.info("No events match the selected filters.")

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ROUTER
# -------------------------------------------------
page = st.session_state.page
_role = st.session_state.get("role", "user")

# Admin-only pages; all other pages are accessible to any authenticated user
_ADMIN_ONLY_PAGES = {"admin", "staff"}
if _role != "admin" and page in _ADMIN_ONLY_PAGES:
    goto("solicitations")

if page == "welcome":
    show_welcome()
elif page == "landing":
    show_landing()
elif page == "operations":
    show_operations()
elif page == "solicitations":
    show_solicitations()
elif page == "shortlisted":
    show_shortlisted()
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
elif page == "staff":
    show_staff()
