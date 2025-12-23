import datetime
import json
import bcrypt
from pathlib import Path
import streamlit as st

# Initialize default admin on first run
from init_admin import create_default_admin
create_default_admin()

from auth import check_access
from data_engine import (
    load_dataset,
    build_full_eda,
    normalize_set_aside_column,
    normalize_opportunity_type_column,
    build_final_output_table,
    to_excel_bytes,
    to_csv_bytes,
    apply_filters,
)
from llm_agent import summarize_dataset, create_llm_plan


# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(
    page_title="Survey Agent",
    page_icon="📊",
    layout="wide",
)

# Load CSS
css_path = Path("assets/style.css")
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# -------------------------------------------------
# AUTH + SESSION STATE
# -------------------------------------------------
check_access()

st.session_state.setdefault("page", "home")
st.session_state.setdefault("results_ready", False)
st.session_state.setdefault("activity_log", [])


def goto(page: str):
    st.session_state.page = page
    st.rerun()


def log_event(action: str, status: str, message: str = "", extra: dict | None = None):
    st.session_state.activity_log.append({
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "role": st.session_state.get("role", "unknown"),
        "action": action,
        "status": status,
        "message": message,
        "extra": extra or {},
    })


# -------------------------------------------------
# USER MANAGEMENT FUNCTIONS (ADMIN ONLY)
# -------------------------------------------------
def hash_password(password: str) -> bytes:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())


def verify_password(password: str, hashed: bytes) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed)


def load_users():
    """Load users from JSON file"""
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        st.error(f"Error loading users: {e}")
        return []


def save_users(users):
    """Save users to JSON file"""
    try:
        with open('users.json', 'w') as f:
            json.dump(users, f, indent=4)
        return True
    except Exception as e:
        st.error(f"Error saving users: {e}")
        return False


def add_user(username: str, password: str, role: str = "user"):
    """Add a new user (admin only)"""
    if st.session_state.get("role") != "admin":
        return False, "Access denied. Only admins can add users."
    
    # Validate input
    if len(username.strip()) < 3:
        return False, "Username must be at least 3 characters long."
    
    if len(password) < 6:
        return False, "Password must be at least 6 characters long."
    
    users = load_users()
    
    # Check if user already exists
    if any(user['username'].lower() == username.lower() for user in users):
        return False, "Username already exists."
    
    # Hash password and create user
    hashed_pw = hash_password(password)
    new_user = {
        'username': username.strip(),
        'password': hashed_pw.decode('utf-8'),
        'role': role,
        'created_at': datetime.datetime.now().isoformat(),
        'created_by': st.session_state.get("username", "unknown")
    }
    
    users.append(new_user)
    
    if save_users(users):
        log_event("add_user", "success", f"Added user: {username}")
        return True, f"User '{username}' added successfully!"
    else:
        return False, "Failed to save user data."


def delete_user(username: str):
    """Delete a user (admin only)"""
    if st.session_state.get("role") != "admin":
        return False, "Access denied. Only admins can delete users."
    
    users = load_users()
    
    # Prevent admin from deleting themselves
    if username == st.session_state.get("username"):
        return False, "You cannot delete your own account."
    
    # Filter out the user to delete
    original_count = len(users)
    users = [user for user in users if user['username'] != username]
    
    if len(users) == original_count:
        return False, f"User '{username}' not found."
    
    if save_users(users):
        log_event("delete_user", "success", f"Deleted user: {username}")
        return True, f"User '{username}' deleted successfully!"
    else:
        return False, "Failed to save user data."


def update_user_role(username: str, new_role: str):
    """Update a user's role (admin only)"""
    if st.session_state.get("role") != "admin":
        return False, "Access denied. Only admins can update user roles."
    
    users = load_users()
    
    for user in users:
        if user['username'] == username:
            old_role = user['role']
            user['role'] = new_role
            user['updated_at'] = datetime.datetime.now().isoformat()
            user['updated_by'] = st.session_state.get("username", "unknown")
            
            if save_users(users):
                log_event("update_user_role", "success", 
                         f"Updated {username} role from {old_role} to {new_role}")
                return True, f"User '{username}' role updated to '{new_role}'!"
            else:
                return False, "Failed to save user data."
    
    return False, f"User '{username}' not found."


# -------------------------------------------------
# EXTERNAL TOOLS UI
# -------------------------------------------------
def render_external_tools():
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem;">
            External AI & Research Tools
        </div>
        <p style="color:#374151; font-size:0.9rem; margin-bottom:0.8rem;">
            Click a tool below to continue your analysis or proposal workflow.
        </p>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
        .ext-btn {
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 0.5rem;
            padding: 0.45rem 0.9rem;
            border-radius: 999px;
            background: #F3F4F6;
            color: #111827 !important;
            border: 1px solid #D1D5DB;
            font-size: 0.85rem;
            text-decoration: none;
            font-weight: 500;
        }
        .ext-btn:hover {
            background: #E5E7EB;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <a class="ext-btn"
           href="https://chatgpt.com/g/g-67df3383b37c81919e4fd38381e15a3b-sources-sought-analyzer"
           target="_blank">Sources Sought Analyzer</a>

        <a class="ext-btn"
           href="https://chatgpt.com/g/g-68c8e4688328819182428ed714ade74a-breakdown-statement-of-works"
           target="_blank">Breakdown Statement of Work</a>

        <a class="ext-btn" href="https://chatgpt.com" target="_blank">ChatGPT</a>

        <a class="ext-btn" href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer" target="_blank">Sam Excel Solicitation Analyzer</a>

        <a class="ext-btn"
           href="https://www.perplexity.ai/"
           target="_blank">Perplexity AI</a>

        <a class="ext-btn" href="https://www.google.com" target="_blank">Google Search</a>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# TRAINING PAGE (VISIBLE TO ALL USERS)
# -------------------------------------------------
def show_training():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    # Header
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Training Videos</div>
            <div class='app-subtitle'>
                Learn how to use SAM.gov, ChatGPT, and federal opportunity tools.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    # Training content
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    st.markdown("### 🎥 How to use Sam.gov and ChatGPT", unsafe_allow_html=True)
    st.video("https://www.youtube.com/watch?v=Nyvwo7es3wo")

    st.markdown(
        "<p style='color:#6B7280; font-size:0.9rem;'>More training videos will be added soon…</p>",
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

    # External tools also shown here
    render_external_tools()

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# HOME PAGE
# -------------------------------------------------
def show_home():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    # Header
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Survey Agent</div>
            <div class='app-subtitle'>
                AI-powered assistant for managing federal opportunity spreadsheets.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Feature Grid
    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    # Document Assistant Card
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>Document Assistant</div>
            <div class='feature-desc'>Upload data, normalize it, and apply AI filters.</div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Document Assistant"):
        goto("survey")
    st.markdown("</div>", unsafe_allow_html=True)

    # Training Card
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>Training</div>
            <div class='feature-desc'>Watch tutorials and learn how to use SAM.gov & AI tools.</div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("View Training"):
        goto("training")
    st.markdown("</div>", unsafe_allow_html=True)

    # Tools card
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>AI Tools</div>
            <div class='feature-desc'>Use specialized AI tools to analyze federal opportunities.</div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Tools"):
        goto("tools")
    st.markdown("</div>", unsafe_allow_html=True)

    # Admin Console (Admins Only)
    if st.session_state.get("role") == "admin":
        st.markdown(
            """
            <div class='feature-card'>
                <div class='feature-title'>Admin Console</div>
                <div class='feature-desc'>Manage users and view system activity.</div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Admin Console"):
            goto("admin")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# TOOLS PAGE (JUST LINK WRAPPER)
# -------------------------------------------------
def show_tools():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>External Tools</div>
            <div class='app-subtitle'>
                Use these tools to support your analysis workflows.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    render_external_tools()

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# DOCUMENT ASSISTANT
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>
                Upload, normalize, filter, and export federal opportunity datasets.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    # Upload
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded_file:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dataset_name = uploaded_file.name

    # Load dataset
    try:
        df = load_dataset(uploaded_file)
    except Exception as e:
        st.error(f"Could not load file: {e}")
        render_external_tools()
        return

    # Dataset info
    st.markdown(
        f"<p class='data-meta'>Loaded <b>{dataset_name}</b> — Rows: {len(df)} | Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    # Build EDA
    eda = build_full_eda(df)

    # Manual Dataset Summary
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Dataset Understanding (Click to Generate)", unsafe_allow_html=True)

    if st.button("Generate Dataset Summary"):
        with st.spinner("AI analyzing your dataset..."):
            try:
                summary = summarize_dataset(eda)
            except Exception as e:
                summary = f"(AI failed: {e})"
        st.write(summary)

    st.markdown("</div>", unsafe_allow_html=True)

    # User instruction
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What do you want to extract or filter?")
    user_request = st.text_area(
        "Instruction",
        placeholder="Example: Show SDVOSB solicitations due in the next 14 days",
        height=120,
    )
    run_btn = st.button("Run Analysis")
    st.markdown("</div>", unsafe_allow_html=True)

    if not run_btn:
        render_external_tools()
        return

    if not user_request.strip():
        st.warning("Please provide an instruction.")
        render_external_tools()
        return

    with st.status("Processing your request...", expanded=True) as status:
        # Step 1: LLM Plan
        status.update(label="Interpreting your instruction...", state="running")
        try:
            plan = create_llm_plan(eda, user_request)
        except Exception as e:
            st.error(f"AI plan failed: {e}")
            return

        columns = plan.get("columns", {})
        sa_patterns = plan.get("set_aside_patterns", {})
        opp_patterns = plan.get("opportunity_type_patterns", {})
        filters = plan.get("filters", [])

        # Step 2: Normalize
        status.update(label="Normalizing...", state="running")
        df2 = df.copy()
        df2 = normalize_set_aside_column(df2, columns.get("set_aside_column") or "TypeOfSetAsideDescription", sa_patterns)
        df2 = normalize_opportunity_type_column(df2, columns.get("opportunity_type_column") or "Type", opp_patterns)

        # Step 3: Build final table
        status.update(label="Building final output...", state="running")
        try:
            final_df = build_final_output_table(df2, columns)
            final_df = apply_filters(final_df, filters)
        except Exception as e:
            st.error(f"Error building output: {e}")
            return

        status.update(label="Complete", state="complete")

    # Output
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Filtered Results", unsafe_allow_html=True)
    st.write(f"Rows returned: **{len(final_df)}**")

    if len(final_df) > 0:
        st.dataframe(final_df.head(50))

        excel_bytes = to_excel_bytes(final_df)
        csv_bytes = to_csv_bytes(final_df)

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "Download Excel",
                excel_bytes,
                "Filtered_Results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.download_button(
                "Download CSV",
                csv_bytes,
                "Filtered_Results.csv",
                mime="text/csv",
            )
    else:
        st.warning("No rows matched your filter criteria.")

    st.markdown("</div>", unsafe_allow_html=True)

    render_external_tools()

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ADMIN PAGE (ENHANCED WITH USER MANAGEMENT)
# -------------------------------------------------
def show_admin():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    if st.session_state.get("role") != "admin":
        st.error("Access denied. Only administrators can access this page.")
        if st.button("Back to home"):
            goto("home")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Admin Console</div>
            <div class='app-subtitle'>Manage users and view system activity.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    # Tabs for different admin functions
    tab1, tab2 = st.tabs(["👥 User Management", "📊 Activity Logs"])

    with tab1:
        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        
        # Add New User Section
        st.markdown("### Add New User")
        with st.form("add_user_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                new_username = st.text_input("Username", placeholder="Enter username")
                new_password = st.text_input("Password", type="password", placeholder="Enter password")
            
            with col2:
                new_role = st.selectbox("Role", ["user", "admin"], index=0)
                st.write("")  # Spacing
                submit_add = st.form_submit_button("Add User", use_container_width=True)
            
            if submit_add:
                if new_username and new_password:
                    success, message = add_user(new_username, new_password, new_role)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
                else:
                    st.warning("Please fill in both username and password.")

        st.markdown("</div>", unsafe_allow_html=True)

        # Current Users Section
        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### Current Users")
        
        users = load_users()
        
        if not users:
            st.info("No users found. Add the first user above.")
        else:
            # Display users in a nice format
            for i, user in enumerate(users):
                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                
                with col1:
                    st.write(f"**{user['username']}**")
                
                with col2:
                    current_role = user['role']
                    new_role = st.selectbox(
                        "Role", 
                        ["user", "admin"], 
                        index=0 if current_role == "user" else 1,
                        key=f"role_{i}"
                    )
                    
                    if new_role != current_role:
                        if st.button("Update Role", key=f"update_{i}"):
                            success, message = update_user_role(user['username'], new_role)
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                
                with col3:
                    created_date = user.get('created_at', 'Unknown')
                    if created_date != 'Unknown':
                        try:
                            created_date = datetime.datetime.fromisoformat(created_date).strftime("%Y-%m-%d")
                        except:
                            created_date = 'Unknown'
                    st.write(f"Created: {created_date}")
                
                with col4:
                    # Prevent admin from deleting themselves
                    if user['username'] != st.session_state.get("username"):
                        if st.button("Delete", key=f"delete_{i}", type="secondary"):
                            success, message = delete_user(user['username'])
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                    else:
                        st.write("*(Current User)*")
                
                st.divider()

        st.markdown("</div>", unsafe_allow_html=True)

    with tab2:
        # Activity Logs Section (existing functionality)
        logs = st.session_state.activity_log

        st.markdown("<div class='app-card'>", unsafe_allow_html=True)
        st.markdown("### Activity Log")

        if not logs:
            st.info("No activity logged yet.")
        else:
            # Convert logs to a more readable format
            import pandas as pd
            df_logs = pd.DataFrame(logs)
            
            # Format timestamp
            if 'timestamp' in df_logs.columns:
                df_logs['timestamp'] = pd.to_datetime(df_logs['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
            
            st.dataframe(df_logs, use_container_width=True)
            
            # Option to clear logs
            if st.button("Clear All Logs", type="secondary"):
                st.session_state.activity_log = []
                st.success("Activity logs cleared.")
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ROUTER
# -------------------------------------------------
if st.session_state.page == "home":
    show_home()
elif st.session_state.page == "survey":
    show_survey()
elif st.session_state.page == "training":
    show_training()
elif st.session_state.page == "tools":
    show_tools()
elif st.session_state.page == "admin":
    show_admin()