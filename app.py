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
    apply_filters
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

# Load Notion-style CSS
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


def goto(page):
    st.session_state.page = page
    st.rerun()


def log_event(action, status, msg="", extra=None):
    st.session_state.activity_log.append({
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "role": st.session_state.get("role", "unknown"),
        "action": action,
        "status": status,
        "message": msg,
        "extra": extra or {},
    })


# -------------------------------------------------
# EXTERNAL TOOLS UI
# -------------------------------------------------
def render_external_tools():
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Continue work in external tools", unsafe_allow_html=True)
    st.markdown(
        """
        <p style="color:#374151; font-size:0.9rem; margin-bottom:0.8rem;">
        These tools open in a new browser tab for additional research or proposal writing.
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
            padding: 0.45rem 0.95rem;
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
        <a class="ext-btn" href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer" target="_blank">Custom Solicitation GPT</a>
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

    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>Survey Agent</div>
            <div class='app-subtitle'>
                Intelligent assistant for federal opportunity spreadsheets.
                Upload a dataset and let AI help analyze and filter it.
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Feature grid
    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    # Document Assistant card
    st.markdown("""
        <div class='feature-card'>
            <div class='feature-title'>Document Assistant</div>
            <div class='feature-desc'>
                Upload a CSV or Excel file and let the AI understand, normalize, 
                and filter your dataset.
            </div>
    """, unsafe_allow_html=True)
    if st.button("Open Document Assistant"):
        goto("survey")
    st.markdown("</div>", unsafe_allow_html=True)

    # External tools card
    st.markdown("""
        <div class='feature-card'>
            <div class='feature-title'>External Tools</div>
            <div class='feature-desc'>
                Quick access to ChatGPT, Gemini, Google, and your solicitation analyzer.
            </div>
    """, unsafe_allow_html=True)
    if st.button("View external tools"):
        goto("links")
    st.markdown("</div>", unsafe_allow_html=True)

    # Admin card (only for admin)
    if st.session_state.get("role") == "admin":
        st.markdown("""
            <div class='feature-card'>
                <div class='feature-title'>Admin Console</div>
                <div class='feature-desc'>
                    View session activity logs for debugging.
                </div>
        """, unsafe_allow_html=True)
        if st.button("Open Admin Console"):
            goto("admin")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)  # end grid
    st.markdown("</div>", unsafe_allow_html=True)  # end shell


# -------------------------------------------------
# SURVEY / DOCUMENT ASSISTANT
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    # Header card
    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>
                Upload a dataset, describe what you want, and download the normalized results.
            </div>
        </div>
    """, unsafe_allow_html=True)

    if st.button("Back to home"):
        goto("home")

    # Upload box
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Load dataset
    try:
        df = load_dataset(uploaded)
    except Exception as e:
        st.error(f"Could not load file: {e}")
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dataset_name = uploaded.name

    st.markdown(
        f"<p class='data-meta'>Loaded <b>{dataset_name}</b> — Rows: {len(df)} | Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    # EDA + AI summary
    with st.spinner("Analyzing dataset..."):
        eda = build_full_eda(df)
        try:
            summary = summarize_dataset(eda)
        except Exception as e:
            summary = f"(AI summary failed: {e})"

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### AI Understanding of Your Dataset")
    st.write(summary)
    st.markdown("</div>", unsafe_allow_html=True)

    # User instruction
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Describe what you want to filter or extract")
    user_request = st.text_area("Instruction", height=120)
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

    # AI PLAN + PROCESSING
    with st.status("Interpreting your instruction...", expanded=True) as status:
        # Step 1: LLM Plan
        try:
            plan = create_llm_plan(eda, user_request)
            cols = plan.get("columns", {})
            sa_patterns = plan.get("set_aside_patterns", {})
            opp_patterns = plan.get("opportunity_type_patterns", {})
            filters = plan.get("filters", [])
            explanation = plan.get("plan_explanation", "")
            status.update(label="Normalizing dataset...", state="running")
        except Exception as e:
            st.error(f"AI planning failed: {e}")
            render_external_tools()
            return

        # Step 2: Normalize dataset
        try:
            df2 = df.copy()
            df2 = normalize_set_aside_column(df2, cols.get("set_aside_column") or "TypeOfSetAsideDescription", sa_patterns)
            df2 = normalize_opportunity_type_column(df2, cols.get("opportunity_type_column") or "Type", opp_patterns)
        except Exception as e:
            st.error(f"Normalization failed: {e}")
            render_external_tools()
            return

        # Step 3: Build final table
        try:
            final_df = build_final_output_table(df2, cols)
            final_df = apply_filters(final_df, filters)
            status.update(label="Complete", state="complete")
        except Exception as e:
            st.error(f"Error building final output: {e}")
            render_external_tools()
            return

    # RESULTS
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What the agent did")
    st.write(explanation)

    st.markdown("#### Filtered Results")
    st.write(f"Rows returned: **{len(final_df)}**")

    if len(final_df) == 0:
        st.warning("No rows matched your filter criteria.")
    else:
        st.dataframe(final_df.head(50))

        excel_bytes = to_excel_bytes(final_df)
        csv_bytes = to_csv_bytes(final_df)

        c1, c2 = st.columns(2)
        with c1:
            st.download_button("Download Excel", excel_bytes, "Filtered_Results.xlsx")
        with c2:
            st.download_button("Download CSV", csv_bytes, "Filtered_Results.csv")

    st.markdown("</div>", unsafe_allow_html=True)

    # Permanent external tools
    render_external_tools()

    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# EXTERNAL TOOLS PAGE
# -------------------------------------------------
def show_links():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>External Tools</div>
            <div class='app-subtitle'>Quick access to research resources.</div>
        </div>
    """, unsafe_allow_html=True)

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
        st.error("Access denied.")
        if st.button("Back to home"):
            goto("home")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>Admin Console</div>
            <div class='app-subtitle'>Session Activity Log</div>
        </div>
    """, unsafe_allow_html=True)

    if st.button("Back to home"):
        goto("home")

    logs = st.session_state.activity_log

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    if not logs:
        st.write("No activity yet.")
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
