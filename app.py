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


# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(
    page_title="Survey Agent",
    page_icon="📊",
    layout="wide"
)

# -------------------------------------------------
# LOAD CSS
# -------------------------------------------------
css_path = Path("assets/style.css")
if css_path.exists():
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# -------------------------------------------------
# LOGIN FIRST
# -------------------------------------------------
check_access()

# -------------------------------------------------
# MAIN APP CONTAINER
# -------------------------------------------------
st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

# -------------------------------------------------
# HEADER
# -------------------------------------------------
st.markdown(
    """
    <div class='app-card'>
        <div class='app-title'>📊 Survey Agent</div>
        <div class='app-subtitle'>
            Upload your spreadsheet, let the AI understand it, normalize set-asides & opportunity types,
            filter based on your request, and export a clean Excel/CSV result.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------
# FILE UPLOAD SECTION
# -------------------------------------------------
st.markdown("<div class='app-card'>", unsafe_allow_html=True)
uploaded_file = st.file_uploader("📂 Upload Excel or CSV", type=["csv", "xlsx", "xls"])
st.markdown("</div>", unsafe_allow_html=True)

if not uploaded_file:
    st.info("Upload a file above to begin.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# Load file
try:
    df = load_dataset(uploaded_file)
except Exception as e:
    st.error(f"File upload failed: {e}")
    st.stop()

st.markdown(
    f"<p class='data-meta'>Loaded <b>{uploaded_file.name}</b> • Rows: {len(df)} • Columns: {len(df.columns)}</p>",
    unsafe_allow_html=True,
)

# -------------------------------------------------
# OPTIONAL DATA PREVIEW
# -------------------------------------------------
with st.expander("Preview first 20 rows"):
    st.dataframe(df.head(20))


# -------------------------------------------------
# AI DATASET SUMMARY SECTION
# -------------------------------------------------
with st.spinner("Analyzing dataset structure..."):
    eda = build_full_eda(df)
    try:
        ai_summary = summarize_dataset(eda)
    except Exception as e:
        ai_summary = f"(AI summary failed: {e})"

st.markdown("<div class='app-card'>", unsafe_allow_html=True)
st.markdown("### 🤖 AI Understanding of Your Dataset", unsafe_allow_html=True)
st.write(ai_summary)
st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# USER PROMPT SECTION
# -------------------------------------------------
st.markdown("<div class='app-card'>", unsafe_allow_html=True)
st.markdown("### 🧠 What do you want to extract or filter?", unsafe_allow_html=True)

user_request = st.text_area(
    "Instruction",
    placeholder="e.g. Give me SDVOSB solicitations between 2024-02-01 and 2024-02-15...",
    height=130
)
run_btn = st.button("🚀 Run analysis")
st.markdown("</div>", unsafe_allow_html=True)


if not run_btn:
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# -------------------------------------------------
# RUN AI PLAN
# -------------------------------------------------
with st.status("Working on your request...", expanded=True) as status:
    status.update(label="🔍 Interpreting your instruction with AI...", state="running")

    try:
        plan = create_llm_plan(eda, user_request)
    except Exception as e:
        st.error(f"AI planning failed: {e}")
        status.update(label="❌ Failed", state="error")
        st.stop()

    columns_map = plan.get("columns", {})
    sa_patterns = plan.get("set_aside_patterns", {})
    opp_patterns = plan.get("opportunity_type_patterns", {})
    plan_explanation = plan.get("plan_explanation", "")

    status.update(label="📚 Normalizing set-asides and types...", state="running")

    set_aside_col = columns_map.get("set_aside_column") or "TypeOfSetAsideDescription"
    type_col = columns_map.get("opportunity_type_column") or "Type"

    df2 = df.copy()
    df2 = normalize_set_aside_column(df2, set_aside_col, ai_patterns=sa_patterns)
    df2 = normalize_opportunity_type_column(df2, type_col, ai_patterns=opp_patterns)

    status.update(label="📦 Building final output table...", state="running")

    final_df = build_final_output_table(df2, columns_map)

    status.update(label="✅ Done!", state="complete")


# -------------------------------------------------
# RESULTS + DOWNLOAD SECTION
# -------------------------------------------------
st.markdown("<div class='app-card'>", unsafe_allow_html=True)
st.markdown("### 📌 What the Agent Did", unsafe_allow_html=True)
st.write(plan_explanation or "AI created column mappings and normalization rules for this dataset.")

st.markdown("### 📋 Filtered & Normalized Results", unsafe_allow_html=True)
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


# -------------------------------------------------
# EMBEDDED CUSTOM GPT SECTION (DIRECTLY UNDER RESULTS)
# -------------------------------------------------
st.markdown("<div class='app-card'>", unsafe_allow_html=True)
st.markdown("### 🧾 Proposal & Write-up Assistant", unsafe_allow_html=True)
st.write("Use the embedded GPT to generate proposals or analyze your exported files.")

components.iframe(
    "https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer",
    height=800,
    scrolling=True,
)

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
