import os
import json
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")

if not API_KEY:
    raise ValueError("OPENAI_API_KEY missing")

client = OpenAI(api_key=API_KEY)


# -------------------------------------------------
# SUMMARIZE DATASET
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    prompt = (
        "Here is a dataset summary:\n"
        f"{eda}\n\n"
        "Explain in plain English what the dataset contains and what fields look important."
    )

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Provide clear analysis."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return r.choices[0].message.content


# -------------------------------------------------
# LLM PLAN (COLUMNS + FILTERS)
# -------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:

    SYSTEM_PROMPT = """
You output ONLY valid JSON matching this schema:

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
  "filters": [],
  "plan_explanation": ""
}

VALID filter operators:
- "in"
- "equals"
- "contains"
- "between"   (dates)
- "next_days" (relative date: e.g., next 2 days, tomorrow, etc.)

Examples:
User: "due in the next 2 days"
→ { "column": "Due Date", "operator": "next_days", "value": 2 }

User: "due between Feb 1 and Feb 3"
→ { "column": "Due Date", "operator": "between", "value": ["2024-02-01", "2024-02-03"] }

Never return markdown or text outside JSON.
"""

    payload = {
        "eda": eda,
        "user_request": user_request,
        "note": "Infer columns and filters based on the dataset summary."
    }

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
        temperature=0.0,
    )

    content = r.choices[0].message.content

    try:
        plan = json.loads(content)
    except:
        plan = {}

    # Guarantee required structures
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("filters", [])
    plan.setdefault("plan_explanation", "")

    return plan
