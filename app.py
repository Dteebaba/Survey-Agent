# app.py
import streamlit as st
import pandas as pd
import io

from data_engine import load_dataset, build_full_eda
from llm_agent import summarize_dataset, create_llm_plan

# --------------------- PAGE CONFIG --------------------- #
st.set_page_config(
    page_title="Opportunity Assistant",
    layout="wide",
)

# --------------------- CUSTOM CSS (Modern Look) --------------------- #
st.markdown(
    """
    <style>
    body {
        background-color: #0f172a;
        color: #e5e7eb;
    }
    .main {
        background-color: #020617;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .app-title {
        font-size: 2rem;
        font-weight: 700;
        color: #e5e7eb;
    }
    .app-subtitle {
        font-size: 0.95rem;
        color: #9ca3af;
    }
    .card {
        background: #020617;
        border-radius: 16px;
        padding: 1.2rem 1.4rem;
        border: 1px solid #1f2937;
        box-shadow: 0 14px 28px rgba(15,23,42,0.6);
    }
    .card-soft {
        background: #020617;
        border-radius: 16px;
        padding: 1rem 1.2rem;
        border: 1px solid #111827;
    }
    .section-title {
        font-size: 1.1rem;
        font-weight: 600;
        color: #e5e7eb;
        margin-bottom: 0.4rem;
    }
    .section-caption {
        font-size: 0.9rem;
        color: #9ca3af;
        margin-bottom: 0.8rem;
    }
    .stButton>button {
        background: linear-gradient(135deg, #6366f1, #ec4899);
        color: white;
        border-radius: 999px;
        border: none;
        padding: 0.45rem 1.2rem;
        font-weight: 600;
    }
    .stButton>button:hover {
        filter: brightness(1.05);
        border: 1px solid #a855f7;
    }
    .pill {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        font-size: 0.75rem;
        background: #111827;
        color: #9ca3af;
        margin-right: 0.35rem;
        margin-bottom: 0.2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------- SIDEBAR MODE SELECT --------------------- #
with st.sidebar:
    st.markdown("<div class='app-title'>Opportunity Assistant</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='app-subtitle'>AI-powered workspace for understanding & transforming federal opportunity spreadsheets.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    mode = st.radio(
        "Choose workspace",
        ["Document Assistant", "AI Writer / Conversation"],
    )
    st.markdown("---")
    st.caption("Powered by OpenAI gpt-4.1-mini")


# --------------------- MODE 1: DOCUMENT ASSISTANT --------------------- #
if mode == "Document Assistant":
    st.markdown("<div class='section-title'>Welcome</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='section-caption'>Upload a federal opportunities spreadsheet, let the AI study it, then describe what you want to extract or create. The platform will return a filtered table and downloadable sheets.</div>",
        unsafe_allow_html=True,
    )

    # Upload card
    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("#### Upload Your Dataset")
        uploaded_file = st.file_uploader(
            "Upload an Excel or CSV file", type=["xlsx", "xls", "csv"]
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if uploaded_file:
        # Load data
        try:
            df = load_dataset(uploaded_file)
        except Exception as e:
            st.error(f"Error loading file: {e}")
            st.stop()

        st.markdown("<div class='card-soft'>", unsafe_allow_html=True)
        st.markdown(
            f"**Loaded file:** `{uploaded_file.name}`  •  **Rows:** {len(df)}  •  **Columns:** {len(df.columns)}"
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # Build EDA and get AI dataset summary
        with st.spinner("Analyzing dataset structure..."):
            eda = build_full_eda(df)
            try:
                ai_summary = summarize_dataset(eda)
            except Exception as e:
                ai_summary = f"(AI summary failed: {e})"

        # Show AI dataset summary in a card
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("#### AI Dataset Understanding")
        st.write(ai_summary)
        st.markdown("</div>", unsafe_allow_html=True)

        # Prompt & Run Analysis
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("#### What do you want to do?")
        st.markdown(
            "<div class='section-caption'>Describe the slice, filters, or output structure you want. For example: 'Give me SDVOSB solicitations between 2024-02-01 and 2024-02-15 with NAICS 541512 and only these columns.'</div>",
            unsafe_allow_html=True,
        )
        user_request = st.text_area(
            "Your instruction:",
            height=120,
            label_visibility="collapsed",
        )
        run_analysis = st.button("Run Analysis")

        st.markdown("</div>", unsafe_allow_html=True)

        if run_analysis and user_request:
            with st.status("Thinking through your request...", expanded=True) as status:
                status.update(label="🔍 Building a plan from your instruction...", state="running")
                try:
                    plan = create_llm_plan(eda, user_request)
                except Exception as e:
                    st.error(f"LLM planning failed: {e}")
                    status.update(label="Planning failed", state="error")
                    st.stop()

                # Pull pieces from plan
                date_col = plan.get("date_column") or ""
                type_col = plan.get("type_column") or ""
                set_col = plan.get("set_aside_column") or ""
                naics_col = plan.get("naics_column") or ""
                filters = plan.get("filters", {}) or {}
                output = plan.get("output", {}) or {}
                plan_explanation = plan.get("plan_explanation", "")

                status.update(label="Applying filters with Python...", state="running")

                working = df.copy()

                # --- Date filter ---
                start_date = filters.get("start_date") or ""
                end_date = filters.get("end_date") or ""
                if date_col and date_col in working.columns and start_date and end_date:
                    try:
                        sd = pd.to_datetime(start_date).date()
                        ed = pd.to_datetime(end_date).date()
                        col_dt = pd.to_datetime(working[date_col], errors="coerce")
                        mask = col_dt.dt.date.between(sd, ed)
                        working = working[mask]
                    except Exception as e:
                        st.warning(f"Could not apply date filter: {e}")

                # --- Opportunity type filter ---
                opp_types = filters.get("opportunity_types") or []
                if type_col and type_col in working.columns and opp_types:
                    col_lower = working[type_col].astype(str).str.lower()
                    type_mask = False
                    for t in opp_types:
                        type_mask = type_mask | col_lower.str.contains(t.lower(), na=False)
                    working = working[type_mask]

                # --- Set-aside filter ---
                set_asides = filters.get("set_asides") or []
                if set_col and set_col in working.columns and set_asides:
                    col_lower = working[set_col].astype(str).str.lower()
                    sa_mask = False
                    for s in set_asides:
                        sa_mask = sa_mask | col_lower.str.contains(s.lower(), na=False)
                    working = working[sa_mask]

                # --- NAICS filter ---
                naics_codes = filters.get("naics_codes") or []
                if naics_col and naics_col in working.columns and naics_codes:
                    col_str = working[naics_col].astype(str)
                    working = working[col_str.isin(naics_codes)]

                # --- Keyword filter ---
                keywords = [k for k in filters.get("keywords", []) if k]
                if keywords:
                    search_cols = [c for c in ["Title", "Description"] if c in working.columns]
                    if search_cols:
                        kw_mask = False
                        for kw in keywords:
                            for col in search_cols:
                                kw_mask = kw_mask | working[col].astype(str).str.contains(kw, case=False, na=False)
                        working = working[kw_mask]

                filtered = working.copy()
                status.update(label=" Analysis complete.", state="complete")

            # --- Results + downloads --- #
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("#### What the AI did")
            if plan_explanation:
                st.write(plan_explanation)
            else:
                st.write("The AI created a filtering plan based on your instruction and the dataset structure.")

            st.markdown("#### Filtered Results")
            st.write(f"Rows after filtering: **{len(filtered)}**")

            if len(filtered) == 0:
                st.warning("No rows match the filters from your request.")
            else:
                st.dataframe(filtered.head(50))

                # Excel export
                main_sheet_name = output.get("main_sheet_name") or "Filtered"
                columns_to_keep = output.get("columns") or list(filtered.columns)
                final_df = filtered[columns_to_keep] if all(
                    c in filtered.columns for c in columns_to_keep
                ) else filtered

                excel_buf = io.BytesIO()
                with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                    final_df.to_excel(writer, index=False, sheet_name=main_sheet_name[:31])
                excel_buf.seek(0)

                st.download_button(
                    " Download Excel",
                    data=excel_buf,
                    file_name="Filtered_Results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                csv_data = final_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    " Download CSV",
                    data=csv_data,
                    file_name="Filtered_Results.csv",
                    mime="text/csv",
                )

            st.markdown("</div>", unsafe_allow_html=True)

    else:
        st.info("Upload a file to begin using the Document Assistant.")


# --------------------- MODE 2: AI WRITER / CONVERSATION --------------------- #
else:
    st.markdown("<div class='section-title'> AI Writer / Conversation</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='section-caption'>Use this space for general AI help: writing proposals, summarizing tasks, brainstorming, or drafting responses. This mode does not use the uploaded dataset.</div>",
        unsafe_allow_html=True,
    )

    from openai import OpenAI
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        st.error("OPENAI_API_KEY missing. Please set it in your environment or Streamlit secrets.")
    else:
        chat_client = OpenAI(api_key=api_key)

        with st.container():
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            user_text = st.text_area("Type your request for the AI writer:", height=180)
            send = st.button(" Ask AI")

            if send and user_text.strip():
                with st.spinner("Thinking..."):
                    resp = chat_client.chat.completions.create(
                        model="gpt-4.1-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a helpful writing and brainstorming assistant. Be clear, concise, and structured.",
                            },
                            {"role": "user", "content": user_text},
                        ],
                        temperature=0.7,
                    )
                    answer = resp.choices[0].message.content
                    st.markdown("####  AI Response")
                    st.write(answer)

            st.markdown("</div>", unsafe_allow_html=True)
