# app.py
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

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


st.set_page_config(
    page_title="Survey Agent",
    page_icon="📊",
    layout="wide"
)

# Load CSS
css_path = Path("assets/style.css")
if css_path.exists():
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Login gate
check_access()

# Init navigation state
if "page" not in st.session_state:
    st.session_state.page = "home"


# ---------- PAGE SWITCHER ----------

def show_home():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>📊 Survey Agent</div>
            <div class='app-subtitle'>
                AI-assisted analytics for federal opportunity spreadsheets. 
                Choose what you want to do below.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
            <div class='feature-card'>
                <div class='feature-title'>📁 Survey / Document Assistant</div>
                <div class='feature-desc'>
                    Upload an Excel/CSV, let the AI understand it, normalize set-asides & opportunity types,
                    and export a clean, filtered table.
                </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Survey Agent"):
            st.session_state.page = "survey"
            st.experimental_rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown(
            """
            <div class='feature-card'>
                <div class='feature-title'>🧾 Proposal Writer</div>
                <div class='feature-desc'>
                    Use your custom GPT to draft proposals and responses based on exported results.
                </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Open Proposal Writer"):
            st.session_state.page = "writer"
            st.experimental_rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def show_survey_agent():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>📁 Survey / Document Assistant</div>
            <div class='app-subtitle'>
                Upload your opportunity spreadsheet, let the AI map the structure, normalize set-asides & types,
                and export only the essential columns.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Home"):
        st.session_state.page = "home"
        st.experimental_rerun()

    # Upload
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Upload Excel or CSV", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded_file:
        st.info("Upload a file to begin.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    try:
        df = load_dataset(uploaded_file)
    except Exception as e:
        st.error(f"Could not load file: {e}")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        f"<p class='data-meta'>Loaded <b>{uploaded_file.name}</b> • Rows: {len(df)} • Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    # EDA + AI summary
    with st.spinner("Analyzing dataset structure..."):
        eda = build_full_eda(df)
        try:
            ai_summary = summarize_dataset(eda)
        except Exception as e:
            ai_summary = f"(AI summary failed: {e})"

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 🤖 AI understanding of your dataset", unsafe_allow_html=True)
    st.write(ai_summary)
    st.markdown("</div>", unsafe_allow_html=True)

    # User instruction
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 🧠 What do you want to extract?", unsafe_allow_html=True)
    user_request = st.text_area(
        "Instruction",
        placeholder="e.g. Give me SDVOSB solicitations between 2024-02-01 and 2024-02-15...",
        height=130,
    )
    run_btn = st.button("🚀 Run analysis")
    st.markdown("</div>", unsafe_allow_html=True)

    if not run_btn:
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not user_request.strip():
        st.warning("Please provide an instruction for the agent.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # AI plan + normalization
    with st.status("Working on your request...", expanded=True) as status:
        status.update(label="🔍 Interpreting your instruction with AI...", state="running")

        try:
            plan = create_llm_plan(eda, user_request)
        except Exception as e:
            st.error(f"AI planning failed: {e}")
            status.update(label="❌ Failed", state="error")
            return

        columns_map = plan.get("columns", {}) or {}
        sa_patterns = plan.get("set_aside_patterns", {}) or {}
        opp_patterns = plan.get("opportunity_type_patterns", {}) or {}
        plan_explanation = plan.get("plan_explanation", "")

        set_aside_col = columns_map.get("set_aside_column") or "TypeOfSetAsideDescription"
        type_col = columns_map.get("opportunity_type_column") or "Type"

        status.update(label="📚 Normalizing set-asides and types...", state="running")

        df2 = df.copy()
        df2 = normalize_set_aside_column(df2, set_aside_col, ai_patterns=sa_patterns)
        df2 = normalize_opportunity_type_column(df2, type_col, ai_patterns=opp_patterns)

        status.update(label="📦 Building final output table...", state="running")

        final_df = build_final_output_table(df2, columns_map)

        status.update(label="✅ Done!", state="complete")

    # Results + download
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 📌 What the agent did", unsafe_allow_html=True)
    st.write(
        plan_explanation
        or "The agent identified likely columns, applied normalization using AI patterns plus safe fallbacks, "
           "and built a clean table with the required columns."
    )

    st.markdown("### 📋 Filtered & normalized results", unsafe_allow_html=True)
    st.write(f"Rows in final output: **{len(final_df)}**")

    if len(final_df) == 0:
        st.warning("No rows left after filtering/normalization.")
    else:
        st.dataframe(final_df.head(50))

        excel_bytes = to_excel_bytes(final_df)
        csv_bytes = to_csv_bytes(final_df)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Download Excel",
                data=excel_bytes,
                file_name="Filtered_Results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with col2:
            st.download_button(
                "📥 Download CSV",
                data=csv_bytes,
                file_name="Filtered_Results.csv",
                mime="text/csv",
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # Embedded GPT directly under downloads
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 🧾 Proposal & write-up assistant", unsafe_allow_html=True)
    st.write("Use your custom GPT below to draft proposals using the exported data.")
    components.iframe(
        "https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer",
        height=800,
        scrolling=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def show_proposal_writer():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>🧾 Proposal Writer</div>
            <div class='app-subtitle'>
                Direct access to your custom GPT for drafting responses, summaries, and proposals.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("← Back to Home"):
        st.session_state.page = "home"
        st.experimental_rerun()

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    components.iframe(
        "https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer",
        height=800,
        scrolling=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ---------- MAIN ROUTER ----------

if st.session_state.page == "home":
    show_home()
elif st.session_state.page == "survey":
    show_survey_agent()
elif st.session_state.page == "writer":
    show_proposal_writer()
