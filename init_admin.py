import json
import bcrypt
import os
from pathlib import Path

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
    hashed_pw = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt())
    
    # Create default admin user
    default_admin = {
        'username': admin_username,
        'password': hashed_pw.decode('utf-8'),
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