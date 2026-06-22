import json
import hashlib
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _get_token():
    return os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN', '')


def _gist_headers():
    return {
        'Authorization': f"token {_get_token()}",
        'Accept': 'application/vnd.github.v3+json'
    }


def _load_from_gist():
    """
    Try to load users from Gist.
    Returns (reachable: bool, users: list).
    reachable=True means we successfully contacted the Gist API.
    """
    gist_id = os.getenv('GIST_ID', '')
    token   = _get_token()

    if not gist_id or not token:
        return False, []

    try:
        resp = requests.get(
            f'https://api.github.com/gists/{gist_id}',
            headers=_gist_headers(),
            timeout=8
        )
        if resp.status_code == 200:
            files = resp.json().get('files', {})
            if 'users.json' in files:
                users = json.loads(files['users.json']['content'])
                return True, users
            # Gist reachable but users.json doesn't exist yet
            return True, []
        print(f"[init_admin] Gist returned HTTP {resp.status_code}")
        return False, []
    except Exception as e:
        print(f"[init_admin] Could not reach Gist: {e}")
        return False, []


def _save_to_gist(users: list):
    gist_id = os.getenv('GIST_ID', '')
    token   = _get_token()
    if not gist_id or not token:
        return
    try:
        resp = requests.patch(
            f'https://api.github.com/gists/{gist_id}',
            headers=_gist_headers(),
            json={'files': {'users.json': {'content': json.dumps(users, indent=2)}}},
            timeout=10
        )
        if resp.status_code == 200:
            print(f"[init_admin] ✅ users.json saved to Gist")
        else:
            print(f"[init_admin] ⚠ Gist save returned {resp.status_code}")
    except Exception as e:
        print(f"[init_admin] Gist save error: {e}")


def create_default_admin():
    """
    Ensure at least the default admin exists.

    Safety rules:
    - If Gist is reachable and has users → use those as truth, never overwrite.
    - If Gist is reachable but empty → create admin and write to Gist.
    - If Gist is NOT reachable → use local cache if available; never write to Gist.
      The local cache is ephemeral on Streamlit Cloud, so on a cold restart with
      no Gist connectivity we log a warning but do NOT create a blank user list.
    """
    gist_reachable, gist_users = _load_from_gist()

    if gist_reachable:
        if gist_users:
            # Gist has users — always treat as source of truth
            try:
                with open('users.json', 'w') as f:
                    json.dump(gist_users, f, indent=4)
            except Exception:
                pass
            print(f"[init_admin] ✅ Loaded {len(gist_users)} user(s) from Gist")
            return

        # Gist is reachable but empty — first-time setup, create default admin
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'changeme123')

        users = [{
            'username':   admin_username,
            'password':   _hash(admin_password),
            'role':       'admin',
            'created_at': '2024-01-01T00:00:00',
            'created_by': 'system'
        }]

        try:
            with open('users.json', 'w') as f:
                json.dump(users, f, indent=4)
        except Exception:
            pass

        _save_to_gist(users)
        print(f"[init_admin] ✅ Default admin '{admin_username}' created and saved to Gist")
        return

    # Gist not reachable — fall back to local cache only, never create/overwrite
    users_file = Path('users.json')
    if users_file.exists():
        try:
            users = json.loads(users_file.read_text())
            if users:
                print(f"[init_admin] ⚠ Gist unreachable — using local cache ({len(users)} users)")
                return
        except Exception:
            pass

    # Neither Gist nor local cache has users — last resort: create admin locally only.
    # We do NOT write to Gist here because we couldn't verify the Gist state.
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'changeme123')

    users = [{
        'username':   admin_username,
        'password':   _hash(admin_password),
        'role':       'admin',
        'created_at': '2024-01-01T00:00:00',
        'created_by': 'system'
    }]

    try:
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=4)
        print(f"[init_admin] ⚠ Gist unreachable — created local-only admin '{admin_username}'")
        print("[init_admin]   Check that GIST_ID and GH_TOKEN are set in Streamlit secrets.")
    except Exception as e:
        print(f"[init_admin] Could not write users.json: {e}")


if __name__ == "__main__":
    create_default_admin()
