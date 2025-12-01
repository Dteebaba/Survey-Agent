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
    raise ValueError("OPENAI_API_KEY missing from environment variables or Streamlit secrets.")

client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# SUMMARIZE DATASET (human-facing text)
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    """
    Ask the LLM for a brief human-readable summary of the dataset.
    """
    prompt = (
        "You are a concise data analyst for federal opportunity spreadsheets.\n"
        "Here is a compact EDA summary of a tabular dataset:\n"
        f"{eda}\n\n"
        "Explain briefly:\n"
        "- What the dataset likely contains\n"
        "- The most important fields (dates, agencies, set-asides, types)\n"
        "- A couple of useful ways it might be filtered."
    )

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "Provide short, clear explanations suited for a busy proposal worker.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    return resp.choices[0].message.content


# -------------------------------------------------
# CREATE LLM PLAN (columns + patterns + filters)
# -------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:
    """
    Generate a deterministic JSON plan with:
      - column mappings
      - set-aside patterns
      - opportunity type patterns
      - filter operators (no date math; Python handles that)
      - a short human explanation
    """

    # Lagos current date (used only as context, Python does the math)
    lagos_tz = pytz.timezone("Africa/Lagos")
    current_date_lagos = datetime.now(lagos_tz).strftime("%Y-%m-%d")

    SYSTEM_PROMPT = f"""
You output ONLY valid JSON.

Python, not you, will compute all date ranges.
Use this Lagos reference date for understanding the context, but DO NOT
calculate explicit date values yourself:

    current_date_lagos = "{current_date_lagos}"

-----------------------------------------------------
REQUIRED JSON SCHEMA
-----------------------------------------------------
Your response MUST be a single JSON object of this form:

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

If you are unsure about any field, leave it as an empty string "" or [].

-----------------------------------------------------
COLUMN MAPPING RULES
-----------------------------------------------------
From the EDA, infer likely raw column names and map them:

- "solicitation_number": notice ID / solicitation number
- "title": title or short description
- "agency": agency / office hierarchy
- "solicitation_date": posted/notice date
- "due_date": response deadline / due date
- "opportunity_type_column": notice type (e.g., Type, Notice Type)
- "set_aside_column": set-aside field (e.g., TypeOfSetAsideDescription)
- "uilink": UI link / workspace link (often 'UiLink')

Only fill keys when you see a strong match.

-----------------------------------------------------
SET-ASIDE NORMALIZATION PATTERNS
-----------------------------------------------------
Fill set_aside_patterns with lowercase substrings that indicate each bucket.
For example:

  "SDVOSB": ["sdvosb", "service-disabled veteran-owned", ...]

This will be used by Python to normalize raw text into one of the
standard categories:

- "SDVOSB"
- "WOSB"
- "TOTAL SMALL BUSINESS SET ASIDE"
- "VETERAN OWNED SMALL BUSINESS (VOSB)"
- "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)"
- "NO SET-ASIDE"

If you are unsure, keep the list empty.

-----------------------------------------------------
OPPORTUNITY TYPE NORMALIZATION PATTERNS
-----------------------------------------------------
opportunity_type_patterns keys (Solicitation, Presolicitation,
Sources Sought, Other) should contain substrings that indicate each type.

Examples:
- "Solicitation": ["solicitation", "combined synopsis/solicitation"]
- "Presolicitation": ["presolicitation"]
- "Sources Sought": ["sources sought", "rfi", "request for information"]

-----------------------------------------------------
FILTER RULES
-----------------------------------------------------
The "filters" value must be a LIST of filter objects.

Each filter object has:
- "column"   (one of the FINAL column names below)
- "operator" (from the allowed list)
- "value"    (string, list, or integer depending on operator; may be omitted for some operators)

FINAL COLUMN NAMES (for filters):
- "Solicitation Number"
- "Title"
- "Agency"
- "Solicitation Date"
- "Due Date"
- "Opportunity Type"
- "Normalized Set Aside"
- "UiLink"

VALID FILTER OPERATORS:
- "equals"
- "in"
- "contains"
- "between"      (value: ["YYYY-MM-DD", "YYYY-MM-DD"])
- "next_days"    (value: integer, e.g., 2)
- "today"
- "tomorrow"
- "yesterday"
- "this_week"
- "last_week"
- "last_7_days"

Python will compute all date math using current_date_lagos.
YOU MUST NOT fabricate explicit dates for relative phrases; just choose the operator.

-----------------------------------------------------
SET-ASIDE FILTERING (BUSINESS FILTERING)
-----------------------------------------------------
If the user explicitly mentions a set-aside, such as:

- "SDVOSB"
- "WOSB"
- "Total Small Business"
- "Small Business Set-Aside"
- "VOSB"
- "EDWOSB"
- "No set-aside"

then create a filter on the final column name "Normalized Set Aside".

Use the exact normalized categories when possible:

- "SDVOSB"
- "WOSB"
- "TOTAL SMALL BUSINESS SET ASIDE"
- "VETERAN OWNED SMALL BUSINESS (VOSB)"
- "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)"
- "NO SET-ASIDE"

Examples:

User: "Show only SDVOSB opportunities"
→ filter:
  {{
    "column": "Normalized Set Aside",
    "operator": "in",
    "value": ["SDVOSB"]
  }}

User: "Show Total Small Business Set-Aside opportunities"
→ filter:
  {{
    "column": "Normalized Set Aside",
    "operator": "in",
    "value": ["TOTAL SMALL BUSINESS SET ASIDE"]
  }}

Do NOT expand "small business" into multiple categories.
Match only the explicit categories you infer from the request.

-----------------------------------------------------
MULTIPLE CONDITIONS
-----------------------------------------------------
If the user request includes multiple conditions, such as:

  "Show SDVOSB solicitations due in the next 14 days"

you MUST return multiple filter objects in the "filters" list, e.g.:

  "filters": [
    {{
      "column": "Normalized Set Aside",
      "operator": "in",
      "value": ["SDVOSB"]
    }},
    {{
      "column": "Due Date",
      "operator": "next_days",
      "value": 14
    }}
  ]

NEVER drop a condition just because you added another.
NEVER merge unrelated filters into a single object.

-----------------------------------------------------
OUTPUT RULES
-----------------------------------------------------
- Return ONLY the JSON object. No extra commentary.
- Use empty strings or empty arrays when unsure.
- plan_explanation should be a short description of what you inferred
  (e.g. which columns are used and which filters are applied).
"""

    payload = {
        "eda": eda,
        "user_request": user_request,
        "current_date_lagos": current_date_lagos,
        "note": "Return operators only; Python handles date math and filtering logic.",
    }

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
        temperature=0.0,
    )

    content = resp.choices[0].message.content

    # Parse JSON safely
    try:
        plan = json.loads(content)
    except Exception:
        plan = {}

    # Ensure required keys exist
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("filters", [])
    plan.setdefault("plan_explanation", "")

    return plan
