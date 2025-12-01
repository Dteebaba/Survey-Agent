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
# LLM: Summarize Dataset (human-facing text)
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    """
    Ask the LLM for a human-readable dataset description.
    """

    prompt = (
        "You are a concise data analyst for federal opportunity datasets.\n"
        "Here is a compact EDA summary:\n"
        f"{eda}\n\n"
        "Explain in plain language:\n"
        "- What this dataset likely contains\n"
        "- Important fields (dates, agencies, set-asides, types)\n"
        "- What kinds of filtering may be possible\n"
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
# LLM: Create structured plan (columns + patterns + filters)
# -------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:
    """
    Produce a deterministic JSON planning object for:
      - column mappings
      - set-aside patterns
      - opportunity type patterns
      - row-level filters based on the user request
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
  "filters": [
    {
      "column": "Normalized Set Aside",
      "operator": "in",
      "value": ["SDVOSB"]
    }
  ],
  "plan_explanation": ""
}

IMPORTANT:

- The EDA describes the RAW columns, but the final Python table uses these standardized column names:
  - "Solicitation Number"
  - "Title"
  - "Agency"
  - "Solicitation Date"
  - "Due Date"
  - "Opportunity Type"
  - "Normalized Set Aside"
  - "UiLink"

- The filters MUST refer to these FINAL column names only.

Allowed operators in "filters":
- "in"        -> value: list of values (e.g. ["SDVOSB", "WOSB"])
- "equals"    -> value: a single scalar (string or number)
- "contains"  -> value: a single string, case-insensitive substring match
- "between"   -> value: list of two ISO8601 date strings ["YYYY-MM-DD", "YYYY-MM-DD"]

Examples:
- Filter to SDVOSB only:
  { "column": "Normalized Set Aside", "operator": "in", "value": ["SDVOSB"] }

- Filter to solicitations between 2024-02-01 and 2024-02-15:
  { "column": "Solicitation Date", "operator": "between", "value": ["2024-02-01", "2024-02-15"] }

- Filter to only "Solicitation" opportunity type:
  { "column": "Opportunity Type", "operator": "in", "value": ["Solicitation"] }

RULES:
- Output ONLY JSON. Never speak outside the object.
- Do NOT use markdown.
- Use empty strings for unknown column names.
- Use empty arrays for unknown patterns.
- Use an empty list for "filters" if you cannot infer anything.
- plan_explanation MUST be a short summarizing sentence of what you intend to filter and normalize.
"""

    user_payload = {
        "eda": eda,
        "user_request": user_request,
        "instruction": (
            "Infer dataset columns and patterns from EDA, and build filters that operate "
            "on the FINAL standardized column names."
        ),
    }

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

    # Ensure base structure
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("filters", [])
    plan.setdefault("plan_explanation", "")

    # Normalize required subkeys
    required_columns = [
        "solicitation_number", "title", "agency", "solicitation_date",
        "due_date", "opportunity_type_column", "set_aside_column", "uilink",
    ]
    for key in required_columns:
        plan["columns"].setdefault(key, "")

    required_sets = [
        "SDVOSB", "WOSB", "TOTAL SMALL BUSINESS SET ASIDE",
        "VETERAN OWNED SMALL BUSINESS (VOSB)",
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)",
        "NO SET-ASIDE",
    ]
    for key in required_sets:
        plan["set_aside_patterns"].setdefault(key, [])

    required_types = ["Solicitation", "Presolicitation", "Sources Sought", "Other"]
    for key in required_types:
        plan["opportunity_type_patterns"].setdefault(key, [])

    # Ensure filters is always a list
    if not isinstance(plan["filters"], list):
        plan["filters"] = []

    return plan
