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

# -------------------------------------------------
# LOAD CUSTOM CSS THEME (Notion-style)
# -------------------------------------------------
css_path = Path("assets/style.css")
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# -------------------------------------------------
# AUTH & SESSION STATE
# -------------------------------------------------
check_access()

st.session_state.setdefault("page", "home")
st.session_state.setdefault("results_ready", False)
st.session_state.setdefault("activity_log", [])


def goto(page: str):
    st.session_state.page = page
    st.rerun()


def log_event(action, status, message="", extra=None):
    st.session_state.activity_log.append({
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "role": st.session_state.get("role", "unknown"),
        "action": action,
        "status": status,
        "message": message,
        "extra": extra or {},
    })


# -------------------------------------------------
# EXTERNAL TOOLS — CLEAN ORIGINAL UI
# -------------------------------------------------
def render_external_tools():
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Continue work in external tools", unsafe_allow_html=True)

    st.markdown(
        """
        <p style="color:#374151; font-size:0.9rem; margin-bottom:0.8rem;">
            These tools open in a new browser tab for proposal writing or further research.
        </p>
        """,
        unsafe_allow_html=True,
    )

    # Original green pill buttons
    st.markdown(
        """
        <style>
        .ext-btn {
            display: inline-block;
            margin-right: 0.6rem;
            margin-bottom: 0.6rem;
            padding: 0.55rem 1.2rem;
            border-radius: 8px;
            background: #0F766E;
            color: white !important;
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 600;
        }
        .ext-btn:hover {
            background: #0d5f58;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <a class="ext-btn"
           href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer"
           target="_blank">Custom Solicitation GPT</a>

        <a class="ext-btn" href="https://chatgpt.com" target="_blank">ChatGPT</a>

        <a class="ext-btn" href="https://gemini.google.com" target="_blank">Gemini</a>

        <a class="ext-btn" href="https://www.google.com" target="_blank">Google Search</a>
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

    # Feature cards grid
    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    # Document Assistant card
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
                Quick access to ChatGPT, Gemini, Google, and your custom solicitation analyzer.
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
                    View session activity logs.
                </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Admin Console"):
            goto("admin")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)  # grid
    st.markdown("</div>", unsafe_allow_html=True)  # shell


# -------------------------------------------------
# SURVEY PAGE (DOCUMENT ASSISTANT)
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    # Header card
    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>
                Upload a dataset, inspect it, describe what you want,
                and download a filtered and normalized sheet.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    # Upload card
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload Excel or CSV file", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Load file
    try:
        df = load_dataset(uploaded)
    except Exception as e:
        st.error(f"Could not load file: {e}")
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dataset_name = uploaded.name
    st.markdown(
        f"<p class='data-meta'>Loaded <b>{dataset_name}</b> • Rows: {len(df)} • Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    # EDA + summary
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

    # User instructions
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What do you want to extract or filter?")
    user_request = st.text_area("Instruction", height=130)
    run_btn = st.button("Run analysis")
    st.markdown("</div>", unsafe_allow_html=True)

    if not run_btn:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not user_request.strip():
        st.warning("Please enter an instruction.")
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Pipeline status box
    with st.status("Working on your request...", expanded=True) as status:
        # Step 1: AI plan
        try:
            status.update(label="Interpreting your instruction...", state="running")
            plan = create_llm_plan(eda, user_request)
            columns = plan.get("columns", {})
            sa_patterns = plan.get("set_aside_patterns", {})
            opp_patterns = plan.get("opportunity_type_patterns", {})
            explanation = plan.get("plan_explanation", "")
        except Exception as e:
            st.error(f"AI planning failure: {e}")
            render_external_tools()
            return

        # Step 2: Normalize
        try:
            status.update(label="Normalizing fields...", state="running")
            df2 = df.copy()
            df2 = normalize_set_aside_column(df2, columns.get("set_aside_column") or "TypeOfSetAsideDescription", sa_patterns)
            df2 = normalize_opportunity_type_column(df2, columns.get("opportunity_type_column") or "Type", opp_patterns)
        except Exception as e:
            st.error(f"Normalization error: {e}")
            render_external_tools()
            return

        # Step 3: Build table
        try:
            status.update(label="Building final output table...", state="running")
            final_df = build_final_output_table(df2, columns)

            # NEW: apply row-level filters from the plan, if any
            filters = plan.get("filters", []) or []
            final_df = apply_filters(final_df, filters)

        except Exception as e:
            st.error(f"Error building final output: {e}")
            render_external_tools()
            return

        status.update(label="Complete", state="complete")


    # Results card
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What the agent did")
    st.write(explanation)

    st.markdown("#### Filtered and normalized results")
    st.write(f"Rows: **{len(final_df)}**")

    if len(final_df) > 0:
        st.dataframe(final_df.head(50))

        excel_bytes = to_excel_bytes(final_df)
        csv_bytes = to_csv_bytes(final_df)

        c1, c2 = st.columns(2)
        with c1:
            st.download_button("Download Excel", excel_bytes, "Filtered_Results.xlsx")
        with c2:
            st.download_button("Download CSV", csv_bytes, "Filtered_Results.csv")
    else:
        st.warning("No rows match your filters.")

    st.markdown("</div>", unsafe_allow_html=True)

    # External tools always visible
    render_external_tools()

    st.markdown("</div>", unsafe_allow_html=True)  # app-shell


# -------------------------------------------------
# LINKS PAGE
# -------------------------------------------------
def show_links():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>External AI & Research Tools</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    render_external_tools()

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
        st.write(f"Total events: **{len(logs)}**")
        st.write(f"Errors: **{sum(1 for e in logs if e['status']=='error')}**")

        st.dataframe([
            {
                "Time": e["timestamp"],
                "Role": e["role"],
                "Action": e["action"],
                "Status": e["status"],
                "Message": e["message"],
                "File": e["extra"].get("file", ""),
            }
            for e in logs
        ])

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
