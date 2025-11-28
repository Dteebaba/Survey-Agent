import os
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in environment / Streamlit secrets.")

client = OpenAI(api_key=OPENAI_API_KEY)


def summarize_dataset(eda: Dict) -> str:
    """
    Ask the LLM to describe the dataset in plain language.
    """
    msg = (
        "You are analyzing a tabular dataset used for federal opportunities / solicitations.\n"
        "Here is a compact EDA summary:\n"
        f"{eda}\n\n"
        "Explain what this dataset seems to contain, what the important columns are (dates, set-asides, types, agencies), "
        "and how it could be filtered for business development purposes."
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


def create_llm_plan(eda: Dict, user_request: str) -> Dict[str, Any]:
    """
    Create a JSON plan with:
      - columns mapping
      - set_aside_column
      - opportunity_type_column
      - date columns
      - set_aside_patterns
      - opportunity_type_patterns
    """
    plan_prompt = f"""
You are helping build a deterministic Python pipeline for a federal solicitation dataset.

We already computed this EDA:
{eda}

The user request is:
\"\"\"{user_request}\"\"\"


1. From the EDA, identify:
   - The column used as solicitation number / notice id.
   - The title / description column.
   - The agency / office column.
   - The solicitation date column (usually PostedDate / NoticeDate).
   - The due date / response deadline column (if present).
   - The opportunity type column (Type, Notice Type, etc.).
   - The set-aside column (TypeOfSetAside, TypeOfSetAsideDescription, etc.).
   - The UiLink column if present.

2. Build a JSON object with:
   {{
     "columns": {{
        "solicitation_number": "...",
        "title": "...",
        "agency": "...",
        "solicitation_date": "...",
        "due_date": "...",
        "opportunity_type_column": "...",
        "set_aside_column": "...",
        "uilink": "..."
     }},
     "set_aside_patterns": {{
        "SDVOSB": [... patterns ...],
        "WOSB": [...],
        "TOTAL SMALL BUSINESS SET ASIDE": [...],
        "VETERAN OWNED SMALL BUSINESS (VOSB)": [...],
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [...],
        "NO SET-ASIDE": [...]
     }},
     "opportunity_type_patterns": {{
        "Solicitation": [...],
        "Presolicitation": [...],
        "Sources Sought": [...],
        "Other": []
     }},
     "plan_explanation": "Short explanation in plain language of how to filter and normalize."
   }}

3. Only include keys you are confident about. Use null for anything that doesn't exist.
4. Return ONLY valid JSON. No commentary.
"""

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You output strict JSON only. No explanations."},
            {"role": "user", "content": plan_prompt},
        ],
        temperature=0.1,
    )
    content = resp.choices[0].message.content

    import json
    try:
        plan = json.loads(content)
    except Exception:
        # Fallback to empty safe structure
        plan = {
            "columns": {},
            "set_aside_patterns": {},
            "opportunity_type_patterns": {},
            "plan_explanation": "AI plan failed to parse; using fallback patterns only.",
        }
    return plan
