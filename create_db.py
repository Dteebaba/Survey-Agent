import sqlite3
import hashlib
import os

# Create the SQLite database if it doesn't exist
if not os.path.exists("app.db"):
    conn = sqlite3.connect("app.db")  # Create a new SQLite database file
    cursor = conn.cursor()

    # Create the users table (username, hashed password, role)
    cursor.execute('''
    CREATE TABLE users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        role TEXT NOT NULL
    )''')

    # Create the admin_logs table to track actions performed by admin
    cursor.execute('''
    CREATE TABLE admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # Check if super admin exists, create if not
    cursor.execute("SELECT * FROM users WHERE username = 'super_admin'")
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                       ('super_admin', hashlib.sha256('super_admin_password'.encode()).hexdigest(), 'admin'))
        conn.commit()

    conn.close()

print("Database setup complete.")
