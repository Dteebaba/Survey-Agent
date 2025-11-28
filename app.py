import streamlit as st
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


# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(
    page_title="Survey Agent",
    page_icon="📊",
    layout="wide"
)

# -------------------------------------------------
# LOAD CUSTOM CSS
# -------------------------------------------------
css_path = Path("assets/style.css")
if css_path.exists():
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# -------------------------------------------------
# AUTHENTICATION
# -------------------------------------------------
check_access()

# -------------------------------------------------
# INIT NAVIGATION STATE
# -------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "home"


def goto(page_name: str):
    st.session_state.page = page_name
    st.rerun()


# -------------------------------------------------
# HOME / DASHBOARD
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

    # Feature 1 — Spreadsheet analysis
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

    # Feature 2 — External tools
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>External AI & Research Tools</div>
            <div class='feature-desc'>
                Open ChatGPT, your custom solicitation analyzer GPT, Gemini, or Google
                in a new browser tab after you have exported your data.
            </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("View links & tools"):
        goto("links")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)  # feature-grid
    st.markdown("</div>", unsafe_allow_html=True)  # app-shell


# -------------------------------------------------
# DOCUMENT / SURVEY ASSISTANT
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>
                Upload a dataset, inspect it, describe what you want, and download a filtered
                and normalized sheet ready for proposal work.
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
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Load dataset
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
    st.markdown("#### AI understanding of your dataset", unsafe_allow_html=True)
    st.write(ai_summary)
    st.markdown("</div>", unsafe_allow_html=True)

    # User instruction
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What do you want to extract or filter?", unsafe_allow_html=True)
    user_request = st.text_area(
        "Instruction",
        placeholder="Example: Filter to SDVOSB solicitations between 2024-02-01 and 2024-02-15 and include only the standard columns.",
        height=130,
    )
    run_btn = st.button("Run analysis")
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
        status.update(label="Interpreting your instruction with AI...", state="running")

        try:
            plan = create_llm_plan(eda, user_request)
        except Exception as e:
            st.error(f"AI planning failed: {e}")
            status.update(label="Failed", state="error")
            return

        columns_map = plan.get("columns", {}) or {}
        sa_patterns = plan.get("set_aside_patterns", {}) or {}
        opp_patterns = plan.get("opportunity_type_patterns", {}) or {}
        plan_explanation = plan.get("plan_explanation", "")

        type_col = columns_map.get("opportunity_type_column") or "Type"
        sa_col = columns_map.get("set_aside_column") or "TypeOfSetAsideDescription"

        status.update(label="Normalizing set-asides and opportunity types...", state="running")

        df2 = df.copy()
        df2 = normalize_set_aside_column(df2, sa_col, ai_patterns=sa_patterns)
        df2 = normalize_opportunity_type_column(df2, type_col, ai_patterns=opp_patterns)

        status.update(label="Building final output table...", state="running")

        final_df = build_final_output_table(df2, columns_map)

        status.update(label="Complete", state="complete")

    # Results & download
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What the agent did", unsafe_allow_html=True)
    st.write(
        plan_explanation
        or "The agent identified likely columns, applied normalization using AI patterns plus safe fallbacks, "
           "and built a clean table with the required columns."
    )

    st.markdown("#### Filtered and normalized results", unsafe_allow_html=True)
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

        st.markdown(
            """
            <p style="font-size:0.9rem;margin-top:0.75rem;">
            After downloading, you can open any of the external tools below in a new browser tab
            to work on proposals, deeper analysis, or general research.
            </p>
            <div class="link-row">
              <a class="link-button" href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer" target="_blank">
                Open custom Solicitation Analyzer (ChatGPT)
              </a>
              <a class="link-button" href="https://chatgpt.com" target="_blank">
                Open ChatGPT
              </a>
              <a class="link-button" href="https://gemini.google.com" target="_blank">
                Open Gemini
              </a>
              <a class="link-button" href="https://www.google.com" target="_blank">
                Open Google Search
              </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)  # result card
    st.markdown("</div>", unsafe_allow_html=True)  # app-shell


# -------------------------------------------------
# EXTERNAL LINKS PAGE (if user opens from home)
# -------------------------------------------------
def show_links():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>External AI & Research Tools</div>
            <div class='app-subtitle'>
                Use these tools after you have exported your filtered dataset from the Document Assistant.
                Each link opens in a separate browser tab.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="link-row">
          <a class="link-button" href="https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer" target="_blank">
            Custom Solicitation Analyzer (ChatGPT)
          </a>
          <a class="link-button" href="https://chatgpt.com" target="_blank">
            ChatGPT
          </a>
          <a class="link-button" href="https://gemini.google.com" target="_blank">
            Gemini
          </a>
          <a class="link-button" href="https://www.google.com" target="_blank">
            Google Search
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
