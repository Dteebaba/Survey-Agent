import json
import hashlib
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def hash_password(password: str) -> str:
    """Hash a password using SHA256"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_gist_config():
    """Get GitHub Gist configuration from environment variables"""
    gist_id = os.getenv('GIST_ID', '')
    github_token = os.getenv('GITHUB_TOKEN', '')
    return {
        'gist_id': gist_id,
        'github_token': github_token,
        'gist_url': f'https://api.github.com/gists/{gist_id}' if gist_id else ''
    }

def check_gist_exists():
    """Check if Gist already has users"""
    config = get_gist_config()
    
    if not config['gist_id'] or not config['github_token']:
        return False, []
    
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
            return True, users
    except Exception as e:
        print(f"Could not check Gist: {e}")
    
    return False, []

def create_default_admin():
    """Create default admin user if not exists"""
    
    # Check if users already exist in Gist
    gist_exists, existing_users = check_gist_exists()
    
    if gist_exists and len(existing_users) > 0:
        print(f"✓ Found {len(existing_users)} users in GitHub Gist")
        # Save locally for offline access
        with open('users.json', 'w') as f:
            json.dump(existing_users, f, indent=4)
        return
    
    # Check local file
    users_file = Path('users.json')
    if users_file.exists():
        try:
            with open(users_file, 'r') as f:
                existing_users = json.load(f)
                if len(existing_users) > 0:
                    print(f"✓ Found {len(existing_users)} users locally")
                    return
        except:
            pass
    
    # Create new admin user
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'changeme123')
    
    hashed_pw = hash_password(admin_password)
    
    default_admin = {
        'username': admin_username,
        'password': hashed_pw,
        'role': 'admin',
        'created_at': '2024-01-01T00:00:00',
        'created_by': 'system'
    }
    
    users = [default_admin]
    
    # Save locally
    with open('users.json', 'w') as f:
        json.dump(users, f, indent=4)
    
    # Save to Gist
    config = get_gist_config()
    if config['gist_id'] and config['github_token']:
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
                print(f"✓ Default admin created in GitHub Gist: {admin_username}")
            else:
                print(f"✓ Default admin created locally: {admin_username} (Gist sync: {response.status_code})")
        except Exception as e:
            print(f"✓ Default admin created locally: {admin_username}")
            print(f"  (Gist sync failed: {e})")
    else:
        print(f"✓ Default admin created locally: {admin_username}")
        print("  (GitHub Gist not configured - set GIST_ID and GITHUB_TOKEN)")

if __name__ == "__main__":
    create_default_admin()
