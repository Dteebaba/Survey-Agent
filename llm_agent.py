import os
import json
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in environment / Streamlit secrets.")

client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------
# SUMMARIZE DATASET (no changes needed)
# ---------------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    msg = (
        "You are analyzing a tabular dataset used for federal opportunities / solicitations.\n"
        "Here is a compact EDA summary:\n"
        f"{eda}\n\n"
        "Explain what this dataset seems to contain, what the important columns are "
        "(dates, set-asides, types, agencies), and how it could be filtered."
    )

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You are a concise data analyst for federal opportunity spreadsheets."},
            {"role": "user", "content": msg},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


# ---------------------------------------------------------
# CREATE LLM PLAN (fully patched)
# ---------------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:
    """
    Generates a deterministic JSON plan the Python code can rely on.
    """

    plan_prompt = {
        "eda": eda,
        "user_request": user_request,
        "instructions": """
Return a JSON object ONLY, following this exact structure:

{
  "columns": {
    "solicitation_number": "",
    "title": "",
    "agency": "",
    "solicitation_date": "",
    "due_date": "",
    "opportunity_type_column": "",
    "set_aside_column": "",
    "uilink": ""
  },
  "set_aside_patterns": {
    "SDVOSB": [],
    "WOSB": [],
    "TOTAL SMALL BUSINESS SET ASIDE": [],
    "VETERAN OWNED SMALL BUSINESS (VOSB)": [],
    "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [],
    "NO SET-ASIDE": []
  },
  "opportunity_type_patterns": {
    "Solicitation": [],
    "Presolicitation": [],
    "Sources Sought": [],
    "Other": []
  },
  "plan_explanation": ""
}

RULES:
- Output ONLY valid JSON. No text outside the JSON.
- Use an empty string for unknown columns.
- Use empty arrays for unknown patterns.
- Plan explanation must be a SHORT sentence.
"""
    }

    # ----- CRITICAL FIX: Force JSON output -----
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        response_format={"type": "json_object"},   # <- Guarantees valid JSON
        messages=[
            {"role": "system", "content": "You output ONLY valid JSON following the schema. No commentary."},
            {"role": "user", "content": json.dumps(plan_prompt)},
        ],
        temperature=0.0,
    )

    content = resp.choices[0].message.content

    # Safety fallback
    try:
        plan = json.loads(content)
    except Exception:
        plan = {
            "columns": {},
            "set_aside_patterns": {},
            "opportunity_type_patterns": {},
            "plan_explanation": "AI plan failed to parse; using fallback patterns only.",
        }

    return plan
