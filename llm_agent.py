import os
import json
from typing import Dict, Any, List

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in environment variables or Streamlit secrets.")

client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# SUMMARIZE DATASET (Human-readable)
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    """
    Ask the LLM for a plain-language summary of the dataset.
    """
    prompt = (
        "You are a concise data analyst for federal opportunity datasets.\n"
        "Here is a compact EDA summary:\n"
        f"{eda}\n\n"
        "Explain in plain language:\n"
        "- What this dataset likely contains\n"
        "- Important fields (dates, agencies, set-asides, types)\n"
        "- What filters might be useful\n"
    )

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Provide short, clear, neutral explanations."},
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
    Produce a deterministic JSON object that contains:
      - column mappings
      - set-aside patterns
      - opportunity type patterns
      - row-level filters derived from the user request
      - a short human explanation
    """

    SYSTEM_PROMPT = """
You output ONLY valid JSON that fits this exact schema:

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

-----------------------------------------------------
COLUMN NAMES FOR FILTERING (FINAL OUTPUT COLUMN NAMES)
-----------------------------------------------------
All filters MUST use these exact names:

- "Solicitation Number"
- "Title"
- "Agency"
- "Solicitation Date"
- "Due Date"
- "Opportunity Type"
- "Normalized Set Aside"
- "UiLink"

-----------------------------------------------------
SUPPORTED FILTER OPERATORS
-----------------------------------------------------

1. "in"
   Example:
   { "column": "Normalized Set Aside", "operator": "in", "value": ["SDVOSB"] }

2. "equals"
   Example:
   { "column": "Agency", "operator": "equals", "value": "USACE" }

3. "contains"
   Example:
   { "column": "Title", "operator": "contains", "value": "construction" }

4. "between"   (only for absolute dates)
   Example:
   { "column": "Solicitation Date", "operator": "between",
     "value": ["2024-02-01", "2024-02-15"] }

5. "next_days"   (for relative dates, e.g. "due soon")
   Examples:
     "due in the next 2 days"       →  value: 2
     "closing tomorrow"             →  value: 1
     "closing in 48 hours"          →  value: 2
     "closing this week"            →  value: 7
     "due soon"                     →  value: 3

-----------------------------------------------------
NATURAL LANGUAGE INTERPRETATION RULES
-----------------------------------------------------
When user uses relative time language like:
- "tomorrow"
- "soon"
- "within X hours"
- "in the next X days"
- "this week"

ALWAYS convert to operator: "next_days".

Absolute date ranges still use operator: "between".

NEVER include markdown, explanations, or commentary outside the JSON.

The "plan_explanation" must be a short plain-English description of the filtering and normalization actions you inferred.
"""

    user_payload = {
        "eda": eda,
        "user_request": user_request,
        "instruction": (
            "Infer raw columns from EDA, map them to standardized names, "
            "produce patterns, and generate row-level filters based strictly on final column names."
        )
    }

    # Force JSON output
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        temperature=0.0,
    )

    content = resp.choices[0].message.content

    try:
        plan = json.loads(content)
    except Exception:
        plan = {}

    # Guarantee required fields
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("filters", [])
    plan.setdefault("plan_explanation", "")

    # ---------------------------------------------------------------------
    # Normalize column keys
    # ---------------------------------------------------------------------
    required_columns = [
        "solicitation_number", "title", "agency", "solicitation_date",
        "due_date", "opportunity_type_column", "set_aside_column", "uilink",
    ]
    for key in required_columns:
        plan["columns"].setdefault(key, "")

    # ---------------------------------------------------------------------
    # Normalize set-aside pattern buckets
    # ---------------------------------------------------------------------
    required_sets = [
        "SDVOSB", "WOSB", "TOTAL SMALL BUSINESS SET ASIDE",
        "VETERAN OWNED SMALL BUSINESS (VOSB)",
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)",
        "NO SET-ASIDE",
    ]
    for key in required_sets:
        plan["set_aside_patterns"].setdefault(key, [])

    # ---------------------------------------------------------------------
    # Normalize opportunity type buckets
    # ---------------------------------------------------------------------
    required_types = ["Solicitation", "Presolicitation", "Sources Sought", "Other"]
    for key in required_types:
        plan["opportunity_type_patterns"].setdefault(key, [])

    # ---------------------------------------------------------------------
    # Ensure filters is a list of dicts
    # ---------------------------------------------------------------------
    if not isinstance(plan["filters"], list):
        plan["filters"] = []

    # Cleanup: ensure each filter has column/operator/value
    cleaned_filters = []
    for f in plan["filters"]:
        if not isinstance(f, dict):
            continue
        if "column" not in f or "operator" not in f or "value" not in f:
            continue
        cleaned_filters.append(f)

    plan["filters"] = cleaned_filters

    return plan
