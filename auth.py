import streamlit as st
import json
import hashlib
import requests
import os


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


def check_access():
    """Username/password login gate."""
    if st.session_state.get("authenticated"):
        return

    st.title("Survey Agent – Sign In")
    st.write("Please enter your username and password.")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login = st.button("Sign In")

    if login:
        if not username or not password:
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
            st.session_state["role"] = user_found["role"]
            st.session_state["username"] = user_found["username"]
            st.success("Login successful. Loading workspace...")
            st.rerun()
        else:
            st.error("Invalid username or password.")
            st.stop()

    st.stop()
