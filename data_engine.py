import io
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime, timedelta
import pytz


# -------------------------------------------------
# UNIVERSAL SAFE DATE CONVERTER
# -------------------------------------------------
def force_date(series: pd.Series) -> pd.Series:
    """
    Convert ANY column into clean datetime.date values.
    Handles:
      - ISO timestamps (2025-12-05T08:00:00-05:00)
      - MM/DD/YYYY strings (11/26/2025)
      - Excel-style floats
      - Empty or invalid values → NaT
    """
    s = pd.to_datetime(series, errors="coerce")
    return s.dt.date


# -------------------------------------------------
# SIMPLE COLUMN PICKER
# -------------------------------------------------
def pick_first_existing(df: pd.DataFrame, *names, default=None):
    for name in names:
        if name and name in df.columns:
            return name
    return default


# -------------------------------------------------
# FILE LOADING
# -------------------------------------------------
def load_dataset(uploaded_file) -> pd.DataFrame:
    """
    Robust CSV/XLSX loader that handles encoding issues.
    """
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        try:
            return pd.read_csv(uploaded_file, encoding="utf-8", engine="python")
        except Exception:
            return pd.read_csv(uploaded_file, encoding="latin1", engine="python")

    if name.endswith(".xlsx") or name.endswith(".xls"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, engine="openpyxl")

    raise ValueError("Unsupported file type. Upload CSV or Excel.")


# -------------------------------------------------
# EDA SUMMARY
# -------------------------------------------------
def build_full_eda(df: pd.DataFrame) -> Dict:
    eda = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": []
    }

    for col in df.columns:
        ser = df[col]
        eda["columns"].append({
            "name": col,
            "dtype": str(ser.dtype),
            "non_null_count": int(ser.notna().sum()),
            "example_values": [str(v) for v in ser.dropna().unique()[:10]]
        })

    return eda


# -------------------------------------------------
# SET-ASIDE NORMALIZATION
# -------------------------------------------------
def _fallback_set_aside_patterns():
    return {
        "SDVOSB": [
            "sdvosb", "service-disabled veteran-owned",
            "service disabled veteran owned", "service-disabled veteran owned"
        ],
        "WOSB": [
            "wosb", "women-owned small business", "women owned small business",
            "women owned sb", "women-owned sb"
        ],
        "TOTAL SMALL BUSINESS SET ASIDE": [
            "total small business", "100% small business",
            "small business set aside", "small business set-aside"
        ],
        "VETERAN OWNED SMALL BUSINESS (VOSB)": [
            "vosb", "veteran owned small business", "veteran-owned small business"
        ],
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [
            "edwosb", "economically disadvantaged women-owned",
            "economically disadvantaged wosb"
        ],
        "NO SET-ASIDE": [
            "no set-aside used", "no set aside used", "none", "unrestricted"
        ],
    }


def normalize_set_aside_column(
    df: pd.DataFrame,
    col: str,
    ai_patterns: Optional[Dict[str, List[str]]] = None,
    new_col: str = "Normalized_Set_Aside"
) -> pd.DataFrame:
    if col not in df.columns:
        df[new_col] = pd.NA
        return df

    base = _fallback_set_aside_patterns()
    ai_patterns = ai_patterns or {}

    for bucket, patterns in ai_patterns.items():
        if patterns:
            base.setdefault(bucket.strip(), []).extend(patterns)

    lowered = df[col].astype(str).str.lower()

    def classify(v):
        v = v.strip().lower()
        if v in ("", "none", "null", "n/a", "na"):
            return None
        for bucket, pats in base.items():
            for p in pats:
                if p.lower() in v:
                    return bucket
        return "NO SET-ASIDE"

    df[new_col] = lowered.apply(classify)
    return df


# -------------------------------------------------
# OPPORTUNITY TYPE NORMALIZATION
# -------------------------------------------------
def _fallback_opp_patterns():
    return {
        "Solicitation": [
            "solicitation", "combined synopsis/solicitation"
        ],
        "Presolicitation": ["presolicitation"],
        "Sources Sought": [
            "sources sought", "rfi", "request for information"
        ]
    }


def normalize_opportunity_type_column(
    df: pd.DataFrame,
    col: str,
    ai_patterns: Optional[Dict[str, List[str]]] = None,
    new_col: str = "Normalized_Opportunity_Type"
) -> pd.DataFrame:
    if col not in df.columns:
        df[new_col] = "Other"
        return df

    patterns = _fallback_opp_patterns()
    ai_patterns = ai_patterns or {}

    for bucket, pats in ai_patterns.items():
        if pats:
            patterns.setdefault(bucket.strip(), []).extend(pats)

    lowered = df[col].astype(str).str.lower()

    def classify(v):
        v = v.strip().lower()
        for bucket, ps in patterns.items():
            for p in ps:
                if p.lower() in v:
                    return bucket
        return "Other"

    df[new_col] = lowered.apply(classify)
    return df


# -------------------------------------------------
# FINAL OUTPUT TABLE
# -------------------------------------------------
def build_final_output_table(
    df: pd.DataFrame,
    column_map: Dict,
    drop_no_set_aside: bool = True
) -> pd.DataFrame:
    """
    Build the final normalized table with consistent columns.
    ALL date fields converted with force_date() to prevent .dt errors.
    """
    tmp = df.copy()

    # Drop rows where set-aside is missing (if requested)
    if drop_no_set_aside and "Normalized_Set_Aside" in tmp.columns:
        tmp = tmp[tmp["Normalized_Set_Aside"].notna()]
        tmp = tmp[tmp["Normalized_Set_Aside"] != "NO SET-ASIDE"]

    # Resolve columns
    sol_num = column_map.get("solicitation_number") or pick_first_existing(
        tmp, "SolicitationNumber", "NoticeId", "NoticeID", "Solicitation_Number"
    )
    title = column_map.get("title") or pick_first_existing(tmp, "Title", "Description")
    agency = column_map.get("agency") or pick_first_existing(tmp, "Agency", "Office", "Agency/Office")

    sol_date = column_map.get("solicitation_date") or pick_first_existing(
        tmp, "PostedDate", "NoticeDate", "SolicitationDate"
    )

    due_date = column_map.get("due_date") or pick_first_existing(
        tmp, "ResponseDeadLine", "DueDate", "ResponseDate"
    )

    uilink = column_map.get("uilink") or pick_first_existing(tmp, "UiLink", "UIlink", "Ui URL")

    final = pd.DataFrame()

    if sol_num in tmp.columns:
        final["Solicitation Number"] = tmp[sol_num]

    if title in tmp.columns:
        final["Title"] = tmp[title]

    if agency in tmp.columns:
        final["Agency"] = tmp[agency]

    if sol_date in tmp.columns:
        final["Solicitation Date"] = force_date(tmp[sol_date])

    if due_date in tmp.columns:
        final["Due Date"] = force_date(tmp[due_date])

    if "Normalized_Opportunity_Type" in tmp.columns:
        final["Opportunity Type"] = tmp["Normalized_Opportunity_Type"]

    if "Normalized_Set_Aside" in tmp.columns:
        final["Normalized Set Aside"] = tmp["Normalized_Set_Aside"]

    if uilink in tmp.columns:
        final["UiLink"] = tmp[uilink]

    # Sorting by type then solicitation date
    if "Opportunity Type" in final.columns:
        cat = pd.Categorical(
            final["Opportunity Type"],
            categories=["Solicitation", "Presolicitation", "Sources Sought", "Other"],
            ordered=True,
        )
        final["_sort"] = cat

        if "Solicitation Date" in final.columns:
            final = final.sort_values(["_sort", "Solicitation Date"])
        else:
            final = final.sort_values(["_sort"])

        final = final.drop(columns=["_sort"])

    return final


# -------------------------------------------------
# FILTER ENGINE (COMPATIBLE WITH UPDATED LLM)
# -------------------------------------------------
def lagos_today():
    return datetime.now(pytz.timezone("Africa/Lagos")).date()


def get_last_week_range():
    today = lagos_today()
    monday_this = today - timedelta(days=today.weekday())
    monday_last = monday_this - timedelta(days=7)
    sunday_last = monday_last + timedelta(days=6)
    return monday_last, sunday_last


def get_this_week_range():
    today = lagos_today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def apply_filters(df: pd.DataFrame, filters: List[Dict]) -> pd.DataFrame:
    """
    Apply filters generated by the LLM.
    Python computes all date math.
    ALWAYS safe with force_date().
    """
    if not filters:
        return df

    out = df.copy()

    for f in filters:
        col = f.get("column")
        op = f.get("operator")
        val = f.get("value")

        if not col or col not in out.columns:
            continue

        # Normalize date columns safely
        if col in ["Due Date", "Solicitation Date"]:
            out[col] = force_date(out[col])

        # IN
        if op == "in":
            if isinstance(val, list):
                out = out[out[col].isin(val)]
            continue

        # EQUALS
        if op == "equals":
            out = out[out[col] == val]
            continue

        # CONTAINS
        if op == "contains":
            s = out[col].astype(str)
            out = out[s.str.contains(str(val), case=False, na=False)]
            continue

        # BETWEEN (explicit dates)
        if op == "between":
            try:
                start = pd.to_datetime(val[0], errors="coerce").date()
                end = pd.to_datetime(val[1], errors="coerce").date()
            except Exception:
                continue

            out = out.dropna(subset=[col])
            out = out[(out[col] >= start) & (out[col] <= end)]
            continue

        # next_days
        if op == "next_days":
            today = lagos_today()
            future = today + timedelta(days=int(val))
            out = out.dropna(subset=[col])
            out = out[(out[col] >= today) & (out[col] <= future)]
            continue

        # today
        if op == "today":
            t = lagos_today()
            out = out.dropna(subset=[col])
            out = out[out[col] == t]
            continue

        # tomorrow
        if op == "tomorrow":
            t = lagos_today() + timedelta(days=1)
            out = out.dropna(subset=[col])
            out = out[out[col] == t]
            continue

        # yesterday
        if op == "yesterday":
            t = lagos_today() - timedelta(days=1)
            out = out.dropna(subset=[col])
            out = out[out[col] == t]
            continue

        # this_week
        if op == "this_week":
            s, e = get_this_week_range()
            out = out.dropna(subset=[col])
            out = out[(out[col] >= s) & (out[col] <= e)]
            continue

        # last_week
        if op == "last_week":
            s, e = get_last_week_range()
            out = out.dropna(subset=[col])
            out = out[(out[col] >= s) & (out[col] <= e)]
            continue

        # last_7_days
        if op == "last_7_days":
            today = lagos_today()
            start = today - timedelta(days=7)
            out = out.dropna(subset=[col])
            out = out[(out[col] >= start) & (out[col] <= today)]
            continue

    return out


# -------------------------------------------------
# EXPORT HELPERS
# -------------------------------------------------
def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Filtered") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buf.seek(0)
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
