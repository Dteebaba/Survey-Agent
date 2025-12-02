import os
import json
from typing import Dict, Any
from datetime import datetime
import pytz

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY missing")


client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# Human-friendly summary
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    prompt = (
        "You are a concise analyst for federal opportunities.\n"
        f"Dataset structure:\n{eda}\n\n"
        "Explain briefly the content and main fields."
    )

    r = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Be concise and clear."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    return r.choices[0].message.content


# -------------------------------------------------
# Create a deterministic plan
# -------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:

    lagos = pytz.timezone("Africa/Lagos")
    current_date_lagos = datetime.now(lagos).strftime("%Y-%m-%d")

    SYSTEM_PROMPT = f"""
You output ONLY valid JSON. Never write explanations outside JSON.

PYTHON performs all date math. DO NOT compute dates yourself.

Use this Lagos reference date ONLY for choosing operators:
    current_date_lagos = "{current_date_lagos}"

-----------------------------------------------------
VALID FINAL COLUMN NAMES (filters MUST use these):
-----------------------------------------------------
"Solicitation Number"
"Title"
"Agency"
"Solicitation Date"
"Due Date"
"Opportunity Type"
"Normalized Set Aside"
"UiLink"

-----------------------------------------------------
VALID RAW COLUMN NAMES FOR MAPPING
-----------------------------------------------------
Solicitation Date can ONLY be mapped from:
- "PostedDate"
- "NoticeDate"
- "SolicitationDate"

Due Date can ONLY be mapped from:
- "ResponseDeadLine"
- "ResponseDate"
- "DueDate"

NEVER map:
- "ArchiveDate"
- "AwardDate"
- "Active"
- "ArchiveType"
- "NaicsCodes"
- or anything that is not clearly a date column.

-----------------------------------------------------
VALID FILTER OPERATORS
-----------------------------------------------------
No date math should be done by you.

You MUST return operators:
- "equals"
- "in"
- "contains"
- "between" (explicit dates)
- "next_days" (int)
- "today"
- "tomorrow"
- "yesterday"
- "this_week"
- "last_week"
- "last_7_days"

EXAMPLES:

"due tomorrow" → {"{"}"column": "Due Date", "operator": "tomorrow"{"}"}

"due in next 14 days" → {"{"}"column": "Due Date", "operator": "next_days", "value": 14{"}"}

"due last week" → {"{"}"column": "Due Date", "operator": "last_week"{"}"}

"due between Feb 1 and Feb 5" →
{{
  "column": "Due Date",
  "operator": "between",
  "value": ["2024-02-01","2024-02-05"]
}}

-----------------------------------------------------
SET-ASIDE FILTERING
-----------------------------------------------------
If user mentions a set-aside category, filter using:

"column": "Normalized Set Aside"
"operator": "in"
"value": ["CATEGORY"]

Valid categories:
- "SDVOSB"
- "WOSB"
- "TOTAL SMALL BUSINESS SET ASIDE"
- "VETERAN OWNED SMALL BUSINESS (VOSB)"
- "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)"
- "NO SET-ASIDE"

Do NOT create semantic groupings. Match ONLY explicit values.

-----------------------------------------------------
MULTIPLE FILTERS
-----------------------------------------------------
If request contains multiple conditions, list multiple filter objects.

Example:
"SDVOSB due in next 14 days" →
"filters": [
  {{"column": "Normalized Set Aside", "operator": "in", "value": ["SDVOSB"]}},
  {{"column": "Due Date", "operator": "next_days", "value": 14}}
]

-----------------------------------------------------
RETURN JSON ONLY
-----------------------------------------------------
Schema to follow:

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
  "set_aside_patterns": {{}},
  "opportunity_type_patterns": {{}},
  "filters": [],
  "plan_explanation": ""
}}
"""

    payload = {
        "eda": eda,
        "user_request": user_request,
        "current_date_lagos": current_date_lagos,
        "note": "Return operators only. Python does ALL date math.",
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
    except Exception:
        plan = {}

    # Ensure structure
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("filters", [])
    plan.setdefault("plan_explanation", "")

    return plan
