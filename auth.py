import streamlit as st
import json
import hashlib
 
def load_users():
    """Load users from JSON file"""
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        return []
 
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
    Username/password authentication using users.json database
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