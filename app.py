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
# INITIALIZE NAVIGATION STATE
# -------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "home"   # Start on dashboard homepage

# -------------------------------------------------
# NAVIGATION HELPER
# -------------------------------------------------
def goto(page_name: str):
    st.session_state.page = page_name
    st.rerun()

# -------------------------------------------------
# TOP NAVBAR (Custom, NOT Streamlit tabs)
# -------------------------------------------------
st.markdown("""
<style>
.navbar {
    background-color: #ffffff;
    padding: 12px 24px;
    border-radius: 16px;
    box-shadow: 0px 2px 12px rgba(0,0,0,0.07);
    display: flex;
    gap: 24px;
    align-items: center;
    margin-bottom: 18px;
}
.nav-item {
    font-weight: 600;
    cursor: pointer;
    padding: 6px 10px;
    border-radius: 8px;
}
.nav-item:hover {
    background-color: #E5E7EB;
}
.active-nav {
    background-color: #D1FAE5;
    color: #065F46;
}
</style>
""", unsafe_allow_html=True)

nav_html = f"""
<div class="navbar">
    <div class="nav-item {'active-nav' if st.session_state.page=='home' else ''}"
         onclick="window.location.href='?nav=home';">
         🏠 Home
    </div>

    <div class="nav-item {'active-nav' if st.session_state.page=='survey' else ''}"
         onclick="window.location.href='?nav=survey';">
         📁 Document Assistant
    </div>

    <div class="nav-item {'active-nav' if st.session_state.page=='writer' else ''}"
         onclick="window.location.href='?nav=writer';">
         🧾 Proposal Writer
    </div>

    <div style="margin-left:auto;" class="nav-item">
        Role: <b>{st.session_state.get('role', 'user')}</b>
    </div>

    <div class="nav-item" onclick="window.location.href='?logout=true';">
        Logout
    </div>
</div>
"""

st.markdown(nav_html, unsafe_allow_html=True)

# Handle redirects
nav_param = st.query_params.get("nav")
logout_param = st.query_params.get("logout")

if nav_param in ["home", "survey", "writer"]:
    st.session_state.page = nav_param
elif logout_param:
    st.session_state.clear()
    st.success("You have been logged out.")
    st.rerun()


# -------------------------------------------------
# PAGE 1: HOME / DASHBOARD
# -------------------------------------------------
def show_home():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>📊 Survey Agent</div>
            <div class='app-subtitle'>
                AI-assisted analytics platform for federal opportunity spreadsheets.
                Choose a workspace below.
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    # Feature 1 — Survey Agent
    st.markdown("""
        <div class='feature-card'>
            <div class='feature-title'>📁 Document Assistant</div>
            <div class='feature-desc'>
                Upload Excel/CSV → AI EDA → normalization → output filtered Excel/CSV.
            </div>
    """, unsafe_allow_html=True)
    if st.button("Open Survey Agent"):
        goto("survey")
    st.markdown("</div>", unsafe_allow_html=True)

    # Feature 2 — Proposal Writer
    st.markdown("""
        <div class='feature-card'>
            <div class='feature-title'>🧾 Proposal Writer</div>
            <div class='feature-desc'>
                Use your custom GPT to write proposals directly inside the app.
            </div>
    """, unsafe_allow_html=True)
    if st.button("Open Proposal Writer"):
        goto("writer")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)



# -------------------------------------------------
# PAGE 2: SURVEY / DOCUMENT ASSISTANT
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>📁 Document Assistant</div>
            <div class='app-subtitle'>
                Upload a dataset → AI analyzes → normalizes → filters → export clean output.
            </div>
        </div>
    """, unsafe_allow_html=True)

    if st.button("← Back to Home"):
        goto("home")

    # Upload
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("📂 Upload Excel or CSV", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded_file:
        return

    # Load
    try:
        df = load_dataset(uploaded_file)
    except Exception as e:
        st.error(f"Failed to load file: {e}")
        return

    st.markdown(
        f"<p class='data-meta'>Loaded <b>{uploaded_file.name}</b> • Rows: {len(df)} • Columns: {len(df.columns)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Preview first 20 rows"):
        st.dataframe(df.head(20))

    # AI summary
    with st.spinner("Analyzing dataset structure..."):
        eda = build_full_eda(df)
        try:
            ai_summary = summarize_dataset(eda)
        except Exception as e:
            ai_summary = f"(AI summary failed: {e})"

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 🤖 AI Dataset Understanding", unsafe_allow_html=True)
    st.write(ai_summary)
    st.markdown("</div>", unsafe_allow_html=True)

    # User instruction
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
        return

    # AI plan
    with st.status("Working on your request...", expanded=True) as status:
        status.update(label="🔍 Interpreting your instruction...", state="running")

        try:
            plan = create_llm_plan(eda, user_request)
        except Exception as e:
            st.error(f"AI planning failed: {e}")
            status.update(label="❌ Failed", state="error")
            return

        columns_map = plan.get("columns", {})
        sa_patterns = plan.get("set_aside_patterns", {})
        opp_patterns = plan.get("opportunity_type_patterns", {})
        plan_explanation = plan.get("plan_explanation", "")

        type_col = columns_map.get("opportunity_type_column") or "Type"
        sa_col = columns_map.get("set_aside_column") or "TypeOfSetAsideDescription"

        status.update(label="📚 Normalizing set-asides & types...", state="running")

        df2 = df.copy()
        df2 = normalize_set_aside_column(df2, sa_col, ai_patterns=sa_patterns)
        df2 = normalize_opportunity_type_column(df2, type_col, ai_patterns=opp_patterns)

        status.update(label="📦 Building final output table...", state="running")

        final_df = build_final_output_table(df2, columns_map)

        status.update(label="✅ Done!", state="complete")

    # Results
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 📌 What the AI Did", unsafe_allow_html=True)
    st.write(plan_explanation or "AI generated column mappings and normalization rules.")

    st.markdown("### 📋 Final Results", unsafe_allow_html=True)
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

    # Embedded GPT directly beneath downloads
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("### 🧾 Proposal & Write-up Assistant", unsafe_allow_html=True)
    st.write("Use your custom GPT to generate proposals using the exported file.")
    components.iframe(
        "https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer",
        height=800,
        scrolling=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# -------------------------------------------------
# PAGE 3: PROPOSAL WRITER (Standalone)
# -------------------------------------------------
def show_writer():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown("""
        <div class='app-card'>
            <div class='app-title'>🧾 Proposal Writer</div>
            <div class='app-subtitle'>
                Your custom GPT is embedded below for writing summaries and proposals.
            </div>
        </div>
    """, unsafe_allow_html=True)

    if st.button("← Back to Home"):
        goto("home")

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    components.iframe(
        "https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer",
        height=800,
        scrolling=True,
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
elif st.session_state.page == "writer":
    show_writer()
