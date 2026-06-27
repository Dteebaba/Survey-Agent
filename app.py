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
# Cached sheet loaders — refreshes every 2 min so changes are visible quickly
# -------------------------------------------------
@st.cache_data(ttl=120, show_spinner=False)
def _fetch_solicitations():
    from google_connector import read_master_sheet
    return read_master_sheet()

@st.cache_data(ttl=120, show_spinner=False)
def _fetch_urgent():
    from google_connector import read_urgent_tab
    return read_urgent_tab()


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
        from agent_state import sync_from_gist, log_user_activity
        sync_from_gist()
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
            if st.session_state.get("role") == "admin":
                goto("landing")
            else:
                goto("solicitations")
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

    if role != "admin":
        goto("solicitations")
        return

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
    c1, c2 = st.columns(2, gap="large")

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
            <p class="hub-card-title">Solicitations</p>
            <p class="hub-card-desc">
                Live view of the master opportunity sheet. Browse all tracked federal
                opportunities and update bid status in real time.
            </p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div class="hub-sol-btn">', unsafe_allow_html=True)
        if st.button("View Solicitations →", use_container_width=True, key="btn_sol"):
            goto("solicitations")
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

    # ── Row 2: remaining tools ────────────────────
    is_admin = st.session_state.get("role") == "admin"
    if is_admin:
        c4, c5, c6 = st.columns(3, gap="medium")
    else:
        c4, _, _ = st.columns(3, gap="medium")

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
    # Count urgent items (due within 10 days)
    _urgent_count = 0
    if "Due Date" in df.columns:
        try:
            from data_engine import force_date
            _due = force_date(df["Due Date"].copy())
            import datetime as _dt_mod
            _today = _dt_mod.date.today()
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

    # Determine what to filter
    _is_urgent_pill = active_pill.startswith("🚨 Urgent")
    active_filter = "All" if _is_urgent_pill else (active_pill.split("  (")[0] if active_pill != "All" else "All")

    display_df = df.copy()
    if _is_urgent_pill and "Due Date" in df.columns:
        try:
            from data_engine import force_date as _fd2
            import datetime as _dt2
            _d2 = _fd2(display_df["Due Date"].copy())
            _t2 = _dt2.date.today()
            display_df = display_df[_d2.notna() & (_d2 >= _t2) & (_d2 < _t2 + _dt2.timedelta(days=10))].reset_index(drop=False)
        except Exception:
            display_df = display_df.reset_index(drop=False)
    elif active_filter != "All" and has_prog:
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
            _actor = st.session_state.get("username", "unknown")

            # Capture changed statuses for activity logging
            _changed = []
            full_df_snap = st.session_state["sol_data"]
            for df_idx, new_val in updates.items():
                row_pos = df_idx - 2  # sheet row → df index
                sol_num = full_df_snap.iloc[row_pos].get("Solicitation Number", "") if row_pos < len(full_df_snap) else ""
                old_val = str(original_prog.iloc[row_pos] if row_pos < len(original_prog) else "")
                _changed.append({"solicitation": str(sol_num), "old_status": old_val, "new_status": str(new_val)})

            def _bg_save(u=updates, r=_save_result, actor=_actor, changed=_changed):
                try:
                    from google_connector import update_progress_reports
                    r["count"] = update_progress_reports(u)
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

    tab_all, tab_urgent = st.tabs(["📋 All Solicitations", "🚨 Urgent (< 10 days)"])

    with tab_all:
        _sol_filter_and_table(df)

    with tab_urgent:
        # Refresh Urgent sheet tab + clear expired in background when user opens it
        if st.button("🔄 Refresh Urgent", key="refresh_urgent"):
            def _bg_urgent():
                try:
                    from google_connector import refresh_urgent_tab, cleanup_overdue_rows
                    cleanup_overdue_rows()
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

# Regular users can only access welcome, landing, and solicitations
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
elif page == "staff":
    show_staff()
