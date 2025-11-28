# auth.py
import streamlit as st


def check_access():
    """
    Simple access-code authentication using [access_codes] in Streamlit secrets.
    Stores role in st.session_state["role"].
    """
    if st.session_state.get("authenticated"):
        return  # already logged in

    st.title("🔐 Survey Agent Login")
    st.write("Enter the access code given to you by the admin.")

    code = st.text_input("Access code", type="password")
    login = st.button("Sign in")

    if login:
        codes = st.secrets.get("access_codes", {})
        if code in codes:
            st.session_state["authenticated"] = True
            st.session_state["role"] = codes[code]  # "admin" / "worker" / etc.
            st.success("Access granted. Loading app...")
            st.rerun()
        else:
            st.error("Invalid access code. Please contact your admin.")
            st.stop()

    st.stop()
