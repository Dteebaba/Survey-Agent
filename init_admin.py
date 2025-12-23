import json
import hashlib
import os
from pathlib import Path
from dotenv import load_dotenv
 
# Load environment variables from .env file
load_dotenv()
 
def hash_password(password: str) -> str:
    """Hash a password using SHA256"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()
 
def create_default_admin():
    """Create default admin user if users.json doesn't exist"""
    users_file = Path('users.json')
    # Only create if file doesn't exist
    if users_file.exists():
        return
    # Get admin credentials from environment variables
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'changeme123')
    # Hash the password
    hashed_pw = hash_password(admin_password)
    # Create default admin user
    default_admin = {
        'username': admin_username,
        'password': hashed_pw,
        'role': 'admin',
        'created_at': '2024-01-01T00:00:00',
        'created_by': 'system'
    }
    # Save to users.json
    with open('users.json', 'w') as f:
        json.dump([default_admin], f, indent=4)
    print(f"✓ Default admin user created: {admin_username}")
 
if __name__ == "__main__":
    create_default_admin()