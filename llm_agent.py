import os
import json
from typing import Dict, Any
from datetime import datetime
import pytz

from dotenv import load_dotenv
from openai import OpenAI

# -------------------------------------------------
# LOAD API KEY
# -------------------------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY missing from Streamlit secrets or .env")

client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# SUMMARIZE DATASET (human-friendly)
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    """
    Ask the LLM for a human-readable summary of the dataset.
    """
    prompt = (
        "You are a concise data analyst. Here is a dataset summary:\n"
        f"{eda}\n\n"
        "Explain briefly:\n"
        "- What the dataset contains\n"
        "- The most important fields\n"
        "- What kinds of filtering might be useful"
    )

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Provide short, clear explanations."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    return r.choices[0].message.content


# -------------------------------------------------
# CREATE LLM PLAN (columns + patterns + filters)
# -------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:
    """
    Generate JSON instructions containing:
      - column mappings
      - normalization patterns
      - filter operators (LLM does NOT compute date math)
      - short human explanation
    """

    # Determine Lagos "today"
    lagos = pytz.timezone("Africa/Lagos")
    lagos_today = datetime.now(lagos).strftime("%Y-%m-%d")

    SYSTEM_PROMPT = f"""
You output ONLY valid JSON.

NEVER calculate date math yourself.
Python will compute all dates using the Lagos reference date below:

    current_date_lagos = "{lagos_today}"

-----------------------------------------------------
VALID FILTER OPERATORS (LLM RETURNS OPERATORS ONLY)
-----------------------------------------------------
- "equals"
- "in"
- "contains"

Relative date filters:
- "today"
- "tomorrow"
- "yesterday"
- "next_days"       (value: integer, e.g. 2)
- "last_week"       (Python computes Monday–Sunday of last week)
- "this_week"
- "last_7_days"

Absolute date range:
- "between"         (value: ["YYYY-MM-DD", "YYYY-MM-DD"])

-----------------------------------------------------
EXAMPLES YOU MUST FOLLOW
-----------------------------------------------------

User says: "due tomorrow"
→ {"{"}"column": "Due Date", "operator": "tomorrow"{"}"}

User says: "due in the next 2 days"
→ {"{"}"column": "Due Date", "operator": "next_days", "value": 2{"}"}

User says: "due last week"
→ {"{"}"column": "Due Date", "operator": "last_week"{"}"}

User says: "due between Feb 1 and Feb 4"
→ {"{"}"column": "Due Date", "operator": "between", "value": ["2024-02-01","2024-02-04"]{"}"}

-----------------------------------------------------
FINAL COLUMN NAMES FOR FILTERING
-----------------------------------------------------
Filters MUST use these EXACT names:

- "Solicitation Number"
- "Title"
- "Agency"
- "Solicitation Date"
- "Due Date"
- "Opportunity Type"
- "Normalized Set Aside"
- "UiLink"

-----------------------------------------------------
REQUIRED JSON SCHEMA
-----------------------------------------------------
{{
  "columns": {{
    "solicitation_number": "",
    "title": "",
    "agency": "",
    "solicitation_date": "",
    "due_date": "",
    "opportunity_type_column": "",
    "set_aside_column": "",
    "uilink": ""
  }},
  "set_aside_patterns": {{
    "SDVOSB": [],
    "WOSB": [],
    "TOTAL SMALL BUSINESS SET ASIDE": [],
    "VETERAN OWNED SMALL BUSINESS (VOSB)": [],
    "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [],
    "NO SET-ASIDE": []
  }},
  "opportunity_type_patterns": {{
    "Solicitation": [],
    "Presolicitation": [],
    "Sources Sought": [],
    "Other": []
  }},
  "filters": [],
  "plan_explanation": ""
}}

-----------------------------------------------------
OUTPUT RULES
-----------------------------------------------------
- Output ONLY JSON. No text outside the JSON object.
- NEVER make up dates.
- ALWAYS use operators (Python computes date ranges).
- Leave fields empty ("") or [] if unknown.
- plan_explanation MUST be short and clear.
"""

    payload = {
        "eda": eda,
        "user_request": user_request,
        "current_date_lagos": lagos_today,
        "note": "Return filter operators only. Do NOT compute dates."
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

    # Ensure required keys
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("filters", [])
    plan.setdefault("plan_explanation", "")

    return plan
