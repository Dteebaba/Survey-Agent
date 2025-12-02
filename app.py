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

# Load custom CSS
css_path = Path("assets/style.css")
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# -------------------------------------------------
# AUTH & SESSION STATE
# -------------------------------------------------
check_access()  # must set st.session_state["role"]

st.session_state.setdefault("page", "home")
st.session_state.setdefault("results_ready", False)
st.session_state.setdefault("activity_log", [])


def goto(page: str):
    st.session_state.page = page
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
# EXTERNAL TOOLS UI
# -------------------------------------------------
def render_external_tools():
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem;">
            Continue work in external tools
        </div>
        <p style="color:#374151; font-size:0.9rem; margin-bottom:0.8rem;">
            These links open in a new tab for deeper analysis or proposal writing.
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
                Intelligent assistant for federal opportunity spreadsheets.
                Upload a dataset and let AI help analyze and filter it.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='feature-grid'>", unsafe_allow_html=True)

    # Document Assistant card
    st.markdown(
        """
        <div class='feature-card'>
            <div class='feature-title'>Document Assistant</div>
            <div class='feature-desc'>
                Upload a CSV or Excel file and let the AI understand, normalize, 
                and filter your dataset into a clean working table.
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
                Quick access to ChatGPT, Gemini, Google, and your solicitation analyzer.
            </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("View external tools"):
        goto("links")
    st.markdown("</div>", unsafe_allow_html=True)

    # Admin console (admins only)
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

    st.markdown("</div>", unsafe_allow_html=True)  # feature-grid
    st.markdown("</div>", unsafe_allow_html=True)  # app-shell


# -------------------------------------------------
# SURVEY / DOCUMENT ASSISTANT
# -------------------------------------------------
def show_survey():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Document Assistant</div>
            <div class='app-subtitle'>
                Upload a dataset, describe what you want,
                and download a filtered, normalized sheet for proposal work.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    # Upload
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"])
    st.markdown("</div>", unsafe_allow_html=True)

    if not uploaded:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    dataset_name = uploaded.name

    # Load dataset
    try:
        df = load_dataset(uploaded)
        log_event("load_dataset", "success", "", {"file": dataset_name})
    except Exception as e:
        msg = f"Could not load file: {e}"
        st.error(msg)
        log_event("load_dataset", "error", msg, {"file": dataset_name})
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        f"<p class='data-meta'>Loaded <b>{dataset_name}</b> — Rows: {len(df)} | Columns: {len(df.columns)}</p>",
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
            log_event("summarize_dataset", "error", str(e), {"file": dataset_name})

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### AI understanding of your dataset", unsafe_allow_html=True)
    st.write(ai_summary)
    st.markdown("</div>", unsafe_allow_html=True)

    # Instruction
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What do you want to extract or filter?", unsafe_allow_html=True)
    user_request = st.text_area(
        "Instruction",
        placeholder=(
            "Example: Filter to SDVOSB opportunities due in the next 14 days "
            "and include only standard columns."
        ),
        height=130,
    )
    run_btn = st.button("Run analysis")
    st.markdown("</div>", unsafe_allow_html=True)

    if not run_btn:
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not user_request.strip():
        st.warning("Please provide an instruction for the agent.")
        render_external_tools()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.session_state.results_ready = False

    # Pipeline
    with st.status("Working on your request...", expanded=True) as status:
        # 1) Plan
        try:
            status.update(label="Interpreting your instruction with AI...", state="running")
            plan = create_llm_plan(eda, user_request)
            columns_map = plan.get("columns", {}) or {}
            sa_patterns = plan.get("set_aside_patterns", {}) or {}
            opp_patterns = plan.get("opportunity_type_patterns", {}) or {}
            filters = plan.get("filters", []) or []
            plan_explanation = plan.get("plan_explanation", "")

            log_event(
                "create_llm_plan",
                "success",
                "",
                {"file": dataset_name, "instruction": user_request},
            )
        except Exception as e:
            msg = f"Failed to create AI plan: {e}"
            st.error(msg)
            log_event(
                "create_llm_plan",
                "error",
                msg,
                {"file": dataset_name, "instruction": user_request},
            )
            status.update(label="Failed to interpret instruction", state="error")
            render_external_tools()
            return

        # 2) Normalization
        try:
            status.update(label="Normalizing set-asides and opportunity types...", state="running")
            df2 = df.copy()

            type_col = columns_map.get("opportunity_type_column") or "Type"
            sa_col = columns_map.get("set_aside_column") or "TypeOfSetAsideDescription"

            df2 = normalize_set_aside_column(df2, sa_col, ai_patterns=sa_patterns)
            df2 = normalize_opportunity_type_column(df2, type_col, ai_patterns=opp_patterns)

            log_event(
                "normalize",
                "success",
                "",
                {"file": dataset_name, "type_col": type_col, "set_aside_col": sa_col},
            )
        except Exception as e:
            msg = f"Normalization failed: {e}"
            st.error(msg)
            log_event(
                "normalize",
                "error",
                msg,
                {"file": dataset_name},
            )
            status.update(label="Normalization failed", state="error")
            render_external_tools()
            return

        # 3) Final output + filters
        try:
            status.update(label="Building final output table...", state="running")
            final_df = build_final_output_table(df2, columns_map)

            # Apply filters from LLM
            final_df = apply_filters(final_df, filters)

            st.session_state.results_ready = True
            log_event(
                "analysis",
                "success",
                "Analysis completed successfully.",
                {
                    "file": dataset_name,
                    "rows_output": len(final_df),
                    "instruction": user_request,
                },
            )

            status.update(label="Complete", state="complete")
        except Exception as e:
            msg = f"Error building final output: {e}"
            st.error(msg)
            log_event(
                "build_final_output_table",
                "error",
                msg,
                {"file": dataset_name},
            )
            status.update(label="Failed to build final table", state="error")
            render_external_tools()
            return

    # Results & download
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### What the agent did", unsafe_allow_html=True)
    st.write(
        plan_explanation
        or "The agent identified likely columns, normalized set-asides and opportunity types, "
           "and applied your filters."
    )

    st.markdown("#### Filtered and normalized results", unsafe_allow_html=True)
    st.write(f"Rows in final output: **{len(final_df)}**")

    if len(final_df) == 0:
        st.warning(
            "No rows remain after applying your instruction and the normalization rules. "
            "You may need to relax the filters or adjust your request."
        )
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

    st.markdown("</div>", unsafe_allow_html=True)  # result card

    # External tools (always visible)
    render_external_tools()

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
                Use these tools after you have exported your filtered dataset 
                from the Document Assistant.
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
# ADMIN CONSOLE (SESSION-LOCAL LOGS)
# -------------------------------------------------
def show_admin():
    st.markdown("<div class='app-shell'>", unsafe_allow_html=True)

    if st.session_state.get("role") != "admin":
        st.markdown(
            """
            <div class='app-card'>
                <div class='app-title'>Admin Console</div>
                <div class='app-subtitle'>
                    You do not have permission to view this area.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Back to home"):
            goto("home")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div class='app-card'>
            <div class='app-title'>Admin Console</div>
            <div class='app-subtitle'>
                Session-level activity log. This data is not persisted between sessions,
                but gives you quick insight into how the tool is being used right now.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Back to home"):
        goto("home")

    logs = st.session_state.activity_log

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)

    if not logs:
        st.write("No activity recorded in this session yet.")
    else:
        total = len(logs)
        errors = sum(1 for e in logs if e["status"] == "error")
        successes = sum(1 for e in logs if e["status"] == "success")

        st.markdown("#### Summary", unsafe_allow_html=True)
        st.write(f"- Total events: **{total}**")
        st.write(f"- Successful analyses: **{successes}**")
        st.write(f"- Errors: **{errors}**")

        st.markdown("#### Detailed activity log", unsafe_allow_html=True)
        log_rows = []
        for e in logs:
            log_rows.append({
                "Time": e["timestamp"],
                "Role": e["role"],
                "Action": e["action"],
                "Status": e["status"],
                "Message": e["message"],
                "File": e["extra"].get("file", ""),
                "Rows Output": e["extra"].get("rows_output", ""),
            })
        st.dataframe(log_rows)

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
