import streamlit as st
import json
import hashlib
import requests
import os

def get_gist_config():
    """Get GitHub Gist configuration from environment variables"""
    gist_id = os.getenv('GIST_ID', '')
    github_token = os.getenv('GITHUB_TOKEN', '')
    return {
        'gist_id': gist_id,
        'github_token': github_token,
        'gist_url': f'https://api.github.com/gists/{gist_id}' if gist_id else ''
    }

def load_users():
    """Load users from GitHub Gist or local file fallback"""
    config = get_gist_config()
    
    # Try GitHub Gist first (if configured)
    if config['gist_id'] and config['github_token']:
        try:
            headers = {
                'Authorization': f"token {config['github_token']}",
                'Accept': 'application/vnd.github.v3+json'
            }
            response = requests.get(config['gist_url'], headers=headers, timeout=5)
            
            if response.status_code == 200:
                gist_data = response.json()
                users_content = gist_data['files']['users.json']['content']
                users = json.loads(users_content)
                
                # Cache locally for offline access
                with open('users.json', 'w') as f:
                    json.dump(users, f, indent=4)
                
                print(f"✓ Loaded {len(users)} users from GitHub Gist")
                return users
        except Exception as e:
            print(f"GitHub Gist error, falling back to local file: {e}")
    
    # Fallback to local file
    try:
        with open('users.json', 'r') as f:
            users = json.load(f)
            print(f"✓ Loaded {len(users)} users from local file")
            return users
    except FileNotFoundError:
        print("No users file found")
        return []
    except Exception as e:
        print(f"Error loading users: {e}")
        return []

def save_users_to_gist(users):
    """Save users to GitHub Gist"""
    config = get_gist_config()
    
    if not config['gist_id'] or not config['github_token']:
        print("⚠ GitHub Gist not configured, saving locally only")
        return False
    
    try:
        headers = {
            'Authorization': f"token {config['github_token']}",
            'Accept': 'application/vnd.github.v3+json'
        }
        
        data = {
            'files': {
                'users.json': {
                    'content': json.dumps(users, indent=2)
                }
            }
        }
        
        response = requests.patch(config['gist_url'], headers=headers, json=data, timeout=5)
        
        if response.status_code == 200:
            print(f"✓ Saved {len(users)} users to GitHub Gist")
            return True
        else:
            print(f"✗ Failed to save to Gist: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Error saving to GitHub Gist: {e}")
        return False

def hash_password(password: str) -> str:
    """Hash a password using SHA256"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    try:
        return hash_password(password) == hashed_password
    except:
        return False

def check_access():
    """
    Username/password authentication using GitHub Gist with local fallback
    """
    if st.session_state.get("authenticated"):
        return  # already logged in

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

    # Stop the rest of the app until authenticated
    st.stop()
