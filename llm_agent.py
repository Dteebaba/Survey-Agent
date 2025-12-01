import os
import json
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in environment variables or Streamlit secrets.")

client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# LLM: Summarize Dataset (Safe)
# -------------------------------------------------
def summarize_dataset(eda: Dict) -> str:
    """
    Ask the LLM for a human-readable dataset description.
    This is NOT JSON. No changes needed here.
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
# LLM: Planning for Column Mapping + Patterns
# -------------------------------------------------
def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:
    """
    Produce a deterministic JSON planning object for:
      - column mappings
      - set-aside patterns
      - opportunity type patterns
      - filtering explanation
    """

    # SINGLE, VERY CLEAR system prompt so model never speaks outside JSON
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
  "plan_explanation": ""
}

RULES:
- Output ONLY JSON. Never speak outside the object.
- Do NOT use markdown.
- Use empty strings for unknown column names.
- Use empty arrays for unknown patterns.
- plan_explanation MUST be a short summarizing sentence.
"""

    user_payload = {
        "eda": eda,
        "user_request": user_request,
        "instruction": "Infer dataset columns and patterns based on the EDA and user request."
    }

    # CRITICAL: response_format forces JSON output
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

    # HARDEN: Guarantee a parsed JSON object
    try:
        plan = json.loads(content)
    except Exception:
        plan = {}

    # Guarantee schema structure even if LLM misses fields
    plan.setdefault("columns", {})
    plan.setdefault("set_aside_patterns", {})
    plan.setdefault("opportunity_type_patterns", {})
    plan.setdefault("plan_explanation", "")

    # Ensure all required keys exist
    required_columns = [
        "solicitation_number", "title", "agency", "solicitation_date",
        "due_date", "opportunity_type_column", "set_aside_column", "uilink"
    ]
    for key in required_columns:
        plan["columns"].setdefault(key, "")

    required_sets = [
        "SDVOSB", "WOSB", "TOTAL SMALL BUSINESS SET ASIDE",
        "VETERAN OWNED SMALL BUSINESS (VOSB)",
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)",
        "NO SET-ASIDE"
    ]
    for key in required_sets:
        plan["set_aside_patterns"].setdefault(key, [])

    required_types = ["Solicitation", "Presolicitation", "Sources Sought", "Other"]
    for key in required_types:
        plan["opportunity_type_patterns"].setdefault(key, [])

    return plan
