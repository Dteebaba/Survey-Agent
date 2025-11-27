import streamlit as st


def check_access():
    """
    Simple access-code authentication using [access_codes] in Streamlit secrets.
    Stores role in st.session_state["role"].
    """
    # Already authenticated
    if st.session_state.get("authenticated"):
        return

    st.title("🔐 Survey Agent Login")
    st.write("Enter the access code provided to you by the admin.")

    code = st.text_input("Access code", type="password")
    login = st.button("Sign in")

    if login:
        codes = st.secrets.get("access_codes", {})
        if code in codes:
            st.session_state["authenticated"] = True
            st.session_state["role"] = codes[code]  # "admin" or "worker"
            st.success("Access granted. Loading app...")
            st.experimental_rerun()
        else:
            st.error("Invalid access code. Please contact your admin.")
            st.stop()

    # Stop the rest of the app from rendering until user logs in
    st.stop()