import datetime
from pathlib import Path
import streamlit as st

from auth import check_access
from data_engine import (
    load_dataset,
    build_full_eda,
    normalize_set_aside_column,
    normalize_opportunity_type_column,
    build_final_output_table,
    to_excel_bytes,
    to_csv_bytes,
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


# -------------------------------------------------
# AUTH & SESSION STATE
# -------------------------------------------------
check_access()  # Enforces authentication

if "page" not in st.session_state:
    st.session_state.page = "home"

if "results_ready" not in st.session_state:
    st.session_state.results_ready = False

if "activity_log" not in st.session_state:
    st.session_state.activity_log = []


def goto(page_name: str):
    st.session_state.page = page_name
    st.rerun()


def log_event(action: str, status: str, message: str = "", extra: dict | None = None):
    entry = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "role": st.session_state.get("role", "unknown"),
        "action": action,
        "status": status,
        "message": message,
        "extra": extra or {},
    }
    st.session_state.activity_log.append(entry)


# -------------------------------------------------
# UI HELPER: External Tools (ALWAYS shown)
# -------------------------------------------------
def insert_external_tools_ui():
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div style="font-size: 1.2rem; font-weight: 700; margin-bottom: 0.5rem; color: #0F766E;">
            External AI & Research Tools
        </div>
        <p style="color:#4B5563; font-size:0.9rem; margin-bottom:1.0rem;">
            Use these tools for deeper solicitation analysis, proposal drafting, or market research.
            These open in a new browser tab.
        </p>
        """,
        unsafe_allow_html=True,
    )

    # CSS + button styling
    st.markdown(
        """
        <style>
        .ext-link-container {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 10px;
        }
        .ext-btn {
            display: flex;
            align-items: center;
            gap: 8px;
            background: #0F766E;
            padding: 10px 18px;
            border-radius: 10px;
            color: #ffffff !important;
            font-size: 0.92rem;
            font-weight: 600;
            text-decoration: none;
            transition: 0.2s ease-in-out;
        }
        .ext-btn:hover {
            background: #0d5f58;
            transform: translateY(-2px);
            box-shadow: 0px 3px 6px rgba(0,0,0,0.18);
        }
        .ext-btn img {
            height: 18px;
            width: 18px;
            border-radius: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Buttons with icons
    st.markdown(
        """
        <div class="ext-link-container">

            <a class="ext-btn"
               href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer"
               target="_blank">
               <img src="https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg">
               Custom Solicitation GPT
            </a>

            <a class="ext-btn" href="https://chatgpt.com" target="_blank">
               <img src="https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg">
               ChatGPT
            </a>

            <a class="ext-btn" href="https://gemini.google.com" target="_blank">
               <img src="https://seeklogo.com/images/G/google-gemini-logo-9A9D5DC93B-seeklogo.com.png">
               Gemini
            </a>

            <a class="ext-btn" href="https://www.google.com" target="_blank">
               <img src="https://upload.wikimedia.org/wikipedia/commons/2/2f/Google_2015_logo.svg">
               Google Search
            </a>

        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# HOME PAGE
# -------------------------------------------------
def show_home():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Survey Agent</div>
            <div class='app-subtitle'>
                Interactive assistant for federal opportunity spreadsheets.
                Start by choosing a workspace below.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    # Document Assistant
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>Document Assistant</div>
            <div class='feature-desc'>
                Upload a CSV / Excel file, let the AI understand the structure,
                normalize set-asides and opportunity types, and export a clean filtered sheet.
            </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Document Assistant"):
        goto("survey")
    st.markdown("</div>", unsafe_allow_html=True)

    # External tools card
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>External AI & Research Tools</div>
            <div class='feature-desc'>
                Quick links to ChatGPT, custom solicitation analyzer, Gemini, and Google.
            </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("View external tools"):
        goto("links")
    st.markdown("</div>", unsafe_allow_html=True)

    # Admin console (admin only)
    if st.session_state.get("role") == "admin":
        st.markdown(
            """
            <div class='feature-card'>
                <div class='feature-title'>Admin Console</div>
                <div class='feature-desc'>
                    View activity logs for this session.
                </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Admin Console"):
            goto("admin")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# SURVEY / DOCUMENT ASSISTANT PAGE
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>
                Upload a dataset, inspect it, describe what you want,
                and download a filtered and normalized sheet ready for proposal work.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    # ---------- Upload block ----------
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Upload Excel or CSV file", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded_file:
        insert_external_tools_ui()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dataset_name = uploaded_file.name

    # ---------- Load dataset ----------
    try:
        df = load_dataset(uploaded_file)
    except Exception as e:
        st.error(f"Could not load file: {e}")
        insert_external_tools_ui()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        f"<p class='data-meta'>Loaded <b>{dataset_name}</b> • Rows: {len(df)} • Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    # ---------- EDA + AI Summary ----------
    with st.spinner("Analyzing dataset structure..."):
        eda = build_full_eda(df)
        try:
            ai_summary = summarize_dataset(eda)
        except Exception as e:
            ai_summary = f"(AI summary failed: {e})"

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### AI understanding of your dataset")
    st.write(ai_summary)
    st.markdown("</div>", unsafe_allow_html=True)

    # ---------- User instructions ----------
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What do you want to extract or filter?")
    user_request = st.text_area(
        "Instruction",
        placeholder="Example: Filter to SDVOSB solicitations between 2024-02-01 and 2024-02-15…",
        height=130,
    )
    run_btn = st.button("Run analysis")
    st.markdown("</div>", unsafe_allow_html=True)

    if not run_btn:
        insert_external_tools_ui()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not user_request.strip():
        st.warning("Please provide an instruction for the agent.")
        insert_external_tools_ui()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.session_state.results_ready = False

    # ---------- AI + Normalization Pipeline ----------
    with st.status("Working on your request...", expanded=True) as status:
        try:
            status.update(label="Interpreting your instruction with AI...", state="running")
            plan = create_llm_plan(eda, user_request)
            columns_map = plan.get("columns", {}) or {}
            sa_patterns = plan.get("set_aside_patterns", {}) or {}
            opp_patterns = plan.get("opportunity_type_patterns", {}) or {}
            plan_explanation = plan.get("plan_explanation", "")
        except Exception as e:
            st.error(f"Failed to create AI plan: {e}")
            insert_external_tools_ui()
            return

        try:
            type_col = columns_map.get("opportunity_type_column") or "Type"
            sa_col = columns_map.get("set_aside_column") or "TypeOfSetAsideDescription"

            status.update(label="Normalizing set-asides and opportunity types...", state="running")

            df2 = df.copy()
            df2 = normalize_set_aside_column(df2, sa_col, ai_patterns=sa_patterns)
            df2 = normalize_opportunity_type_column(df2, type_col, ai_patterns=opp_patterns)
        except Exception as e:
            st.error(f"Error during normalization: {e}")
            insert_external_tools_ui()
            return

        try:
            status.update(label="Building final output table...", state="running")
            final_df = build_final_output_table(df2, columns_map)
        except Exception as e:
            st.error(f"Failed to build final output: {e}")
            insert_external_tools_ui()
            return

        status.update(label="Complete", state="complete")
        st.session_state.results_ready = True

    # ---------- Results + Downloads ----------
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What the agent did")
    st.write(plan_explanation)

    st.markdown("#### Filtered and normalized results")
    st.write(f"Rows in final output: **{len(final_df)}**")

    if len(final_df) == 0:
        st.warning("No rows remain after filtering. Adjust your instructions.")
    else:
        st.dataframe(final_df.head(50))

        excel_bytes = to_excel_bytes(final_df)
        csv_bytes = to_csv_bytes(final_df)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "Download Excel",
                data=excel_bytes,
                file_name="Filtered_Results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with col2:
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name="Filtered_Results.csv",
                mime="text/csv",
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # ---------- ALWAYS-SHOW EXTERNAL TOOLS ----------
    insert_external_tools_ui()

    st.markdown("</div>", unsafe_allow_html=True)  # app-shell


# -------------------------------------------------
# EXTERNAL LINKS PAGE
# -------------------------------------------------
def show_links():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>External AI & Research Tools</div>
            <div class='app-subtitle'>
                These tools open in a separate tab.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    insert_external_tools_ui()

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ADMIN PAGE
# -------------------------------------------------
def show_admin():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    if st.session_state.get("role") != "admin":
        st.error("Access denied")
        if st.button("Back to home"):
            goto("home")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Admin Console</div>
            <div class='app-subtitle'>Session activity log</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    logs = st.session_state.activity_log

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    if not logs:
        st.write("No activity recorded.")
    else:
        total = len(logs)
        errors = sum(1 for e in logs if e["status"] == "error")
        successes = sum(1 for e in logs if e["status"] == "success")

        st.markdown("#### Summary")
        st.write(f"- Total events: **{total}**")
        st.write(f"- Successes: **{successes}**")
        st.write(f"- Errors: **{errors}**")

        st.markdown("#### Detailed Log")
        table = [
            {
                "Time": e["timestamp"],
                "Role": e["role"],
                "Action": e["action"],
                "Status": e["status"],
                "Message": e["message"],
                "File": e["extra"].get("file", ""),
                "Rows Output": e["extra"].get("rows_output", ""),
            }
            for e in logs
        ]

        st.dataframe(table)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# ROUTER
# -------------------------------------------------
if st.session_state.page == "home":
    show_home()
elif st.session_state.page == "survey":
    show_survey()
elif st.session_state.page == "links":
    show_links()
elif st.session_state.page == "admin":
    show_admin()
