import streamlit as st
import json
import hashlib
import hmac
import base64
import requests
import os
from datetime import datetime, timedelta

try:
    import extra_streamlit_components as stx
    _COOKIES_AVAILABLE = True
except ImportError:
    _COOKIES_AVAILABLE = False

_SESSION_COOKIE      = "almor_session"
_INACTIVITY_MINUTES  = 10   # session expires after this many idle minutes
_COOKIE_HOURS        = 8    # browser stores the cookie for 8 hours


# ── Cookie helpers ────────────────────────────────────────────────────────────

def _cm():
    """Return a CookieManager instance (one per Streamlit session via key)."""
    if not _COOKIES_AVAILABLE:
        return None
    return stx.CookieManager(key="almor_auth_cm")


def _pack_session(username: str, role: str) -> str:
    payload = json.dumps({
        "u": username,
        "r": role,
        "t": datetime.utcnow().isoformat(),
    }, separators=(",", ":"))
    secret = _session_secret()
    if not secret:
        return ""
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        + "."
        + base64.urlsafe_b64encode(signature).decode("ascii")
    )


def _session_secret() -> bytes | None:
    """Use deployment credentials to sign browser sessions."""
    value = os.getenv("SESSION_SECRET") or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    return value.encode("utf-8") if value else None


def _unpack_session(raw: str):
    """Return (username, role) or (None, None) if expired or invalid."""
    try:
        encoded_payload, encoded_signature = raw.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload.encode("ascii"))
        signature = base64.urlsafe_b64decode(encoded_signature.encode("ascii"))
        secret = _session_secret()
        if not secret:
            return None, None
        expected = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None, None
        d = json.loads(payload.decode("utf-8"))
        age = (datetime.utcnow() - datetime.fromisoformat(d["t"])).total_seconds()
        if age > _INACTIVITY_MINUTES * 60:
            return None, None
        return d["u"], d["r"]
    except Exception:
        return None, None


def _set_session_cookie(cm, username: str, role: str):
    try:
        value = _pack_session(username, role)
        if not value:
            return
        cm.set(
            _SESSION_COOKIE,
            value,
            expires_at=datetime.now() + timedelta(hours=_COOKIE_HOURS),
            key="set_sc",
        )
    except Exception:
        pass


def clear_auth_cookie():
    """Delete the session cookie — call on sign-out."""
    cm = _cm()
    if cm:
        try:
            cm.delete(_SESSION_COOKIE, key="del_sc")
        except Exception:
            pass


def get_gist_config():
    gist_id = os.getenv('GIST_ID', '')
    # Accept either GITHUB_TOKEN or GH_TOKEN so Streamlit Cloud and GitHub Actions both work
    github_token = os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN', '')
    return {
        'gist_id': gist_id,
        'github_token': github_token,
        'gist_url': f'https://api.github.com/gists/{gist_id}' if gist_id else ''
    }


def _gist_headers():
    config = get_gist_config()
    return {
        'Authorization': f"token {config['github_token']}",
        'Accept': 'application/vnd.github.v3+json'
    }


def load_users():
    """Load users from GitHub Gist (source of truth), with local cache fallback."""
    config = get_gist_config()

    if config['gist_id'] and config['github_token']:
        try:
            response = requests.get(config['gist_url'], headers=_gist_headers(), timeout=8)
            if response.status_code == 200:
                gist_data = response.json()
                if 'users.json' in gist_data.get('files', {}):
                    users = json.loads(gist_data['files']['users.json']['content'])
                    # Refresh local cache
                    try:
                        with open('users.json', 'w') as f:
                            json.dump(users, f, indent=4)
                    except Exception:
                        pass
                    return users
        except Exception as e:
            print(f"Gist load error, using local cache: {e}")

    # Local cache fallback (only used when Gist is unreachable)
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"Error loading local users cache: {e}")
        return []


def save_users_to_gist(users) -> bool:
    """Save users to GitHub Gist. Returns True only if save actually succeeded."""
    config = get_gist_config()

    if not config['gist_id'] or not config['github_token']:
        print("⚠ Gist not configured (GIST_ID or GH_TOKEN missing)")
        return False

    try:
        data = {
            'files': {
                'users.json': {
                    'content': json.dumps(users, indent=2)
                }
            }
        }
        response = requests.patch(
            config['gist_url'], headers=_gist_headers(), json=data, timeout=10
        )
        if response.status_code == 200:
            print(f"✓ Saved {len(users)} users to GitHub Gist")
            return True
        else:
            print(f"✗ Gist save failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Gist save error: {e}")
        return False


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return hash_password(password) == hashed_password
    except Exception:
        return False


_LOGIN_CSS = """
<style>
/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stDecoration"] { display: none !important; }

/* ── Animated gradient background ── */
[data-testid="stAppViewContainer"] {
    background: linear-gradient(-45deg, #0B1120, #112240, #0F3460, #1A1A2E);
    background-size: 400% 400%;
    animation: bgShift 14s ease infinite;
    min-height: 100vh;
}
@keyframes bgShift {
    0%   { background-position: 0%   50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0%   50%; }
}

/* ── Remove default page padding ── */
.main .block-container {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    max-width: 100% !important;
}

/* ── Floating orbs (decorative) ── */
[data-testid="stAppViewContainer"]::before,
[data-testid="stAppViewContainer"]::after {
    content: "";
    position: fixed;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.18;
    pointer-events: none;
    z-index: 0;
    animation: floatOrb 10s ease-in-out infinite alternate;
}
[data-testid="stAppViewContainer"]::before {
    width: 500px; height: 500px;
    background: #1E90FF;
    top: -100px; left: -100px;
}
[data-testid="stAppViewContainer"]::after {
    width: 400px; height: 400px;
    background: #C9A227;
    bottom: -80px; right: -80px;
    animation-delay: -5s;
}
@keyframes floatOrb {
    from { transform: translate(0, 0) scale(1); }
    to   { transform: translate(40px, 40px) scale(1.1); }
}

/* ── Card: the middle column becomes the glass card ── */
div[data-testid="column"]:nth-child(2) {
    background: rgba(255, 255, 255, 0.04) !important;
    backdrop-filter: blur(24px) !important;
    -webkit-backdrop-filter: blur(24px) !important;
    border: 1px solid rgba(255, 255, 255, 0.10) !important;
    border-radius: 24px !important;
    padding: 2.5rem 2rem !important;
    box-shadow: 0 32px 64px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.1) !important;
    position: relative;
    z-index: 1;
    margin-top: 10vh !important;
}

/* ── Input labels ── */
div[data-testid="column"]:nth-child(2) .stTextInput label {
    color: rgba(255,255,255,0.55) !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
}

/* ── Input fields ── */
div[data-testid="column"]:nth-child(2) .stTextInput input {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 10px !important;
    color: #FFFFFF !important;
    font-size: 0.95rem !important;
    padding: 0.7rem 1rem !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
div[data-testid="column"]:nth-child(2) .stTextInput input:focus {
    border-color: #C9A227 !important;
    box-shadow: 0 0 0 3px rgba(201,162,39,0.18) !important;
    background: rgba(255,255,255,0.09) !important;
}
div[data-testid="column"]:nth-child(2) .stTextInput input::placeholder {
    color: rgba(255,255,255,0.25) !important;
}

/* ── Sign In button ── */
div[data-testid="column"]:nth-child(2) .stButton > button {
    background: linear-gradient(135deg, #C9A227 0%, #E8C547 100%) !important;
    color: #0B1120 !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.75rem 1rem !important;
    font-weight: 800 !important;
    font-size: 0.95rem !important;
    letter-spacing: 0.06em !important;
    width: 100% !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 4px 20px rgba(201,162,39,0.3) !important;
}
div[data-testid="column"]:nth-child(2) .stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 30px rgba(201,162,39,0.5) !important;
}
div[data-testid="column"]:nth-child(2) .stButton > button:active {
    transform: translateY(0) !important;
}

/* ── Error / success alerts inside card ── */
div[data-testid="column"]:nth-child(2) .stAlert {
    border-radius: 10px !important;
    font-size: 0.85rem !important;
}

/* ── Divider line ── */
.login-divider {
    border: none;
    border-top: 1px solid rgba(255,255,255,0.10);
    margin: 1.5rem 0;
}
</style>
"""

_LOGIN_BRAND = """
<div style="text-align:center; margin-bottom:2rem;">
    <div style="
        display:inline-flex; align-items:center; justify-content:center;
        width:72px; height:72px; border-radius:18px;
        background:linear-gradient(135deg,#1E3A5F,#0F3460);
        border:2px solid rgba(201,162,39,0.5);
        box-shadow:0 8px 32px rgba(0,0,0,0.4);
        font-size:2rem; margin-bottom:1.1rem;">
        🏛️
    </div>
    <h1 style="
        color:#FFFFFF; font-size:1.85rem; font-weight:900;
        letter-spacing:0.12em; margin:0 0 0.25rem 0;
        text-shadow:0 2px 12px rgba(0,0,0,0.4);">
        ALMOR LLC
    </h1>
    <p style="color:rgba(255,255,255,0.45); font-size:0.82rem;
              margin:0 0 0.9rem 0; letter-spacing:0.04em;">
        Federal Opportunity Intelligence
    </p>
    <span style="
        display:inline-block;
        background:rgba(201,162,39,0.12);
        border:1px solid rgba(201,162,39,0.4);
        color:#C9A227; font-size:0.65rem; font-weight:700;
        letter-spacing:0.12em; padding:0.3rem 0.9rem;
        border-radius:20px; text-transform:uppercase;">
        ★ Service-Disabled Veteran-Owned
    </span>
    <hr class="login-divider" style="margin-top:1.5rem;">
    <p style="color:rgba(255,255,255,0.35); font-size:0.78rem; margin:0;">
        Sign in to access your workspace
    </p>
</div>
"""

_LOGIN_FOOTER = """
<div style="text-align:center; margin-top:1.5rem;">
    <p style="color:rgba(255,255,255,0.2); font-size:0.7rem; margin:0; letter-spacing:0.04em;">
        © 2025 Almor LLC · All rights reserved
    </p>
</div>
"""


def check_access():
    """Username/password login gate with cookie-based session persistence."""

    # ── Already authenticated this session ─────────────────────────────────
    # Do NOT create CookieManager here — if a Sign Out button fires in the
    # same render cycle, clear_auth_cookie() will create one too, causing a
    # StreamlitDuplicateElementKey on the shared "almor_auth_cm" key.
    if st.session_state.get("authenticated"):
        return

    # ── Not yet authenticated — safe to create the CookieManager now ───────
    cm = _cm()

    # ── Try to restore from cookie (survives tab close / refresh) ──────────
    if cm:
        try:
            raw = cm.get(_SESSION_COOKIE)
        except Exception:
            raw = None

        # CookieManager is a React component — on the first render after a page
        # refresh the browser cookie data may not have arrived yet. Allow up to
        # 2 extra reruns before concluding there is no valid cookie.
        if raw is None:
            _tries = st.session_state.get("_auth_tries", 0)
            if _tries < 2:
                st.session_state["_auth_tries"] = _tries + 1
                st.rerun()
                return
        st.session_state.pop("_auth_tries", None)

        if raw:
            username, role = _unpack_session(raw)
            if username:
                current_user = next(
                    (u for u in load_users() if u.get("username", "").lower() == username.lower()),
                    None,
                )
                if not current_user:
                    try:
                        cm.delete(_SESSION_COOKIE, key="del_invalid_sc")
                    except Exception:
                        pass
                    username = None
                else:
                    username = current_user["username"]
                    role = current_user.get("role", "user")
            if username:
                st.session_state["authenticated"] = True
                st.session_state["username"]      = username
                st.session_state["role"]          = role
                _set_session_cookie(cm, username, role)
                st.rerun()
                return

    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    # Three-column layout — middle column becomes the glass card
    _, card, _ = st.columns([1, 1.1, 1])

    with card:
        st.markdown(_LOGIN_BRAND, unsafe_allow_html=True)

        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        st.write("")
        login = st.button("Sign In →", use_container_width=True)

        st.markdown(_LOGIN_FOOTER, unsafe_allow_html=True)

    if login:
        if not username or not password:
            with card:
                st.error("Please enter both username and password.")
            st.stop()

        users = load_users()
        user_found = None
        for user in users:
            if user['username'].lower() == username.lower():
                if verify_password(password, user['password']):
                    user_found = user
                    break

        if user_found:
            st.session_state["authenticated"] = True
            st.session_state["role"]          = user_found["role"]
            st.session_state["username"]      = user_found["username"]
            if cm:
                _set_session_cookie(cm, user_found["username"], user_found["role"])
            st.rerun()
        else:
            with card:
                st.error("Invalid username or password.")
            st.stop()

    st.stop()
