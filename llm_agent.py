# llm_agent.py
import os
import json
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in .env")

client = OpenAI(api_key=OPENAI_API_KEY)

MODEL_NAME = "gpt-4.1-mini"


# ---------- DATASET SUMMARY (EDA INTERPRETATION) ----------

SUMMARY_SYSTEM_PROMPT = """
You are an expert data analyst for federal contracting datasets.

You will receive a Python-style JSON object named "eda" that includes:
- shape (row & column counts)
- column names and dtypes
- sample rows
- unique values per column
- candidate role columns (date, type, set-aside, naics, etc.)

Your job:
1. Explain in clear, simple language what this dataset appears to represent.
2. Highlight the most important columns and what they seem to mean.
3. Identify likely:
   - main date column(s)
   - opportunity type column(s)
   - set-aside column(s)
   - NAICS column(s)
4. Mention any potential issues (e.g. many missing values, multiple possible date columns, etc.).

Output:
- A short human-readable summary (2–5 short paragraphs).
- Use bullet points where useful.
- DO NOT output code or JSON, only explanation text.
"""


def summarize_dataset(eda: Dict[str, Any]) -> str:
    """Ask the model to interpret the EDA and return a human summary."""
    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"eda": eda})},
    ]
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


# ---------- PLAN CREATION (PROMPT → FILTER PLAN) ----------

PLAN_SYSTEM_PROMPT = """
You are a data planning assistant.

You will receive:
- "eda": a JSON summary of the dataset (columns, sample rows, unique values, inferred roles)
- "user_request": a natural-language instruction describing what the user wants

Your job:
1. Decide which columns to use for:
   - date filtering (e.g. PostedDate, ResponseDeadLine, etc.)
   - opportunity type (e.g. Type, BaseType)
   - set-aside (e.g. TypeOfSetAside, SetAsideCode)
   - NAICS (e.g. NaicsCode, NaicsCodes)

2. Parse filters from user_request:
   - date range (start_date, end_date in yyyy-mm-dd)
   - list of normalized opportunity types, e.g. ["Solicitation", "Presolicitation", "Sources Sought", "Other"]
   - set-asides (strings to match: e.g. ["SDVOSB", "WOSB", "TOTAL_SMALL_BUSINESS", "VOSB", "NONE"])
   - list of NAICS codes (6-digit strings)
   - list of free-text keywords to search in title/description

3. Decide which columns should appear in the main output sheet.
4. Optionally suggest additional sheets (like a simple summary), but keep it minimal.

Return ONLY valid JSON in this structure:

{
  "date_column": "name or empty string",
  "type_column": "name or empty string",
  "set_aside_column": "name or empty string",
  "naics_column": "name or empty string",
  "filters": {
    "start_date": "yyyy-mm-dd or empty string",
    "end_date": "yyyy-mm-dd or empty string",
    "opportunity_types": ["Solicitation", "Sources Sought"],
    "set_asides": ["SDVOSB", "WOSB"],
    "naics_codes": ["541512"],
    "keywords": ["generator", "maintenance"]
  },
  "output": {
    "main_sheet_name": "Filtered",
    "columns": ["NoticeId", "Title", "Type", "TypeOfSetAside", "PostedDate", "ResponseDeadLine"]
  },
  "plan_explanation": "Short natural language explanation of how you will filter and structure the output."
}

Rules:
- All fields must exist (use empty string or [] when unknown).
- Only use column names that exist in the eda['columns'] list.
- Do NOT invent columns.
- Return JSON only, no extra text.
"""


def create_llm_plan(eda: Dict[str, Any], user_request: str) -> Dict[str, Any]:
    """
    Ask gpt-4.1-mini to create a structured plan for how to filter and output the data.
    """
    payload = {
        "eda": eda,
        "user_request": user_request,
    }

    messages = [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload)},
    ]

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    content = resp.choices[0].message.content
    plan = json.loads(content)
    return plan
