import io
from typing import Dict, List, Optional
import pandas as pd


# -------------------------------------------------
# SAFE HELPERS
# -------------------------------------------------

def safe_to_datetime(series):
    """
    Safely convert any column to datetime without errors.
    Returns a pandas Series of python date objects.
    """
    s = pd.to_datetime(series, errors="coerce")

    # Force conversion away from object dtype (mixed cells edge cases)
    if s.dtype == "object":
        try:
            s = s.astype("datetime64[ns]")
        except Exception:
            s = pd.to_datetime(s, errors="coerce")

    return s.dt.date


def pick_first_existing(df: pd.DataFrame, *candidates, default=None):
    """
    Returns the first column name that exists in df.
    """
    for c in candidates:
        if c and c in df.columns:
            return c
    return default


# -------------------------------------------------
# FILE LOADING
# -------------------------------------------------

def load_dataset(uploaded_file) -> pd.DataFrame:
    """
    Robust loader for CSV, XLSX, XLS files.
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

    raise ValueError("Unsupported file type. Please upload CSV or Excel (.xlsx/.xls).")


# -------------------------------------------------
# EDA SUMMARY
# -------------------------------------------------

def build_full_eda(df: pd.DataFrame) -> Dict:
    """
    Build a compact EDA summary for the LLM.
    """
    summary = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": []
    }

    for col in df.columns:
        series = df[col]
        summary["columns"].append({
            "name": col,
            "dtype": str(series.dtype),
            "non_null_count": int(series.notna().sum()),
            "example_values": [str(v) for v in series.dropna().unique()[:10]],
        })

    return summary


# -------------------------------------------------
# NORMALIZATION — SET-ASIDE
# -------------------------------------------------

def _fallback_set_aside_patterns():
    return {
        "SDVOSB": [
            "sdvosb", "service-disabled veteran-owned", "service disabled veteran owned",
            "service-disabled veteran owned"
        ],
        "WOSB": [
            "wosb", "women-owned small business", "women owned small business",
            "women owned sb", "women-owned sb"
        ],
        "TOTAL SMALL BUSINESS SET ASIDE": [
            "total small business", "100% small business", "small business set aside",
            "small business set-aside", "total sb"
        ],
        "VETERAN OWNED SMALL BUSINESS (VOSB)": [
            "vosb", "veteran owned small business", "veteran-owned small business",
            "veteran owned sb", "veteran-owned sb"
        ],
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [
            "edwosb", "economically disadvantaged women-owned", "economically disadvantaged wosb"
        ],
        "NO SET-ASIDE": ["no set-aside used", "no set aside used", "none", "unrestricted"],
    }


def normalize_set_aside_column(df: pd.DataFrame, col: str,
                               ai_patterns: Optional[Dict[str, List[str]]] = None,
                               new_col: str = "Normalized_Set_Aside"):

    if col not in df.columns:
        df[new_col] = pd.NA
        return df

    base = _fallback_set_aside_patterns()
    ai_patterns = ai_patterns or {}

    # Merge AI-suggested patterns
    for bucket, plist in ai_patterns.items():
        if not plist:
            continue
        bucket = bucket.strip()
        base.setdefault(bucket, []).extend(plist)

    lower_series = df[col].astype(str).str.lower().fillna("")

    def match(v):
        v = v.strip().lower()
        if v in ("", "none", "null", "n/a", "na"):
            return None
        for bucket, pats in base.items():
            for p in pats:
                if p and p.lower() in v:
                    return bucket
        return "NO SET-ASIDE"

    df[new_col] = lower_series.apply(match)
    return df


# -------------------------------------------------
# NORMALIZATION — OPPORTUNITY TYPE
# -------------------------------------------------

def _fallback_opp_patterns():
    return {
        "Solicitation": ["solicitation", "combined synopsis/solicitation"],
        "Presolicitation": ["presolicitation"],
        "Sources Sought": ["sources sought", "rfi", "request for information"],
    }


def normalize_opportunity_type_column(df: pd.DataFrame, col: str,
                                      ai_patterns: Optional[Dict[str, List[str]]] = None,
                                      new_col: str = "Normalized_Opportunity_Type"):

    if col not in df.columns:
        df[new_col] = "Other"
        return df

    patterns = _fallback_opp_patterns()
    ai_patterns = ai_patterns or {}

    # Merge AI patterns
    for bucket, plist in ai_patterns.items():
        if not plist:
            continue
        bucket = bucket.strip()
        patterns.setdefault(bucket, []).extend(plist)

    lower_series = df[col].astype(str).str.lower().fillna("")

    def classify(v):
        v = v.strip().lower()
        for bucket, pats in patterns.items():
            for p in pats:
                if p and p.lower() in v:
                    return bucket
        return "Other"

    df[new_col] = lower_series.apply(classify)
    return df


# -------------------------------------------------
# FINAL OUTPUT BUILDER
# -------------------------------------------------

def build_final_output_table(df: pd.DataFrame, column_map: Dict, drop_no_set_aside=True):
    """
    Creates a clean final output table with standardized column names.
    """

    tmp = df.copy()

    # Optionally filter out "NO SET-ASIDE"
    if drop_no_set_aside and "Normalized_Set_Aside" in tmp.columns:
        tmp = tmp[tmp["Normalized_Set_Aside"].notna()]
        tmp = tmp[tmp["Normalized_Set_Aside"] != "NO SET-ASIDE"]

    # Column lookup
    sol_num = column_map.get("solicitation_number") or pick_first_existing(
        tmp, "SolicitationNumber", "NoticeId", "NoticeID", "Solicitation_Number"
    )

    title = column_map.get("title") or pick_first_existing(tmp, "Title", "Description")
    agency = column_map.get("agency") or pick_first_existing(
        tmp, "Agency", "Office", "Agency/Office"
    )

    sol_date = column_map.get("solicitation_date") or pick_first_existing(
        tmp, "PostedDate", "NoticeDate", "SolicitationDate"
    )

    due_date = column_map.get("due_date") or pick_first_existing(
        tmp, "ResponseDeadLine", "DueDate", "ResponseDate"
    )

    ui = column_map.get("uilink") or pick_first_existing(
        tmp, "UiLink", "UIlink", "Ui URL"
    )

    final = pd.DataFrame()

    if sol_num in tmp.columns:
        final["Solicitation Number"] = tmp[sol_num]
    if title in tmp.columns:
        final["Title"] = tmp[title]
    if agency in tmp.columns:
        final["Agency"] = tmp[agency]

    if sol_date in tmp.columns:
        final["Solicitation Date"] = safe_to_datetime(tmp[sol_date])
    if due_date in tmp.columns:
        final["Due Date"] = safe_to_datetime(tmp[due_date])

    if "Normalized_Opportunity_Type" in tmp.columns:
        final["Opportunity Type"] = tmp["Normalized_Opportunity_Type"]

    if "Normalized_Set_Aside" in tmp.columns:
        final["Normalized Set Aside"] = tmp["Normalized_Set_Aside"]

    if ui in tmp.columns:
        final["UiLink"] = tmp[ui]

    # Sorting
    if "Opportunity Type" in final.columns:
        cat = pd.Categorical(
            final["Opportunity Type"],
            categories=["Solicitation", "Presolicitation", "Sources Sought", "Other"],
            ordered=True,
        )
        final["_order"] = cat

        if "Solicitation Date" in final.columns:
            final = final.sort_values(["_order", "Solicitation Date"])
        else:
            final = final.sort_values(["_order"])

        final = final.drop(columns=["_order"])

    return final

# -------------------------------------------------
# Filters
# -------------------------------------------------

def apply_filters(df: pd.DataFrame, filters: List[Dict]) -> pd.DataFrame:
    """
    Apply a list of simple filter objects to the final output DataFrame.

    Each filter is expected to have:
      - column: name of the column in df (e.g. 'Normalized Set Aside')
      - operator: one of 'in', 'equals', 'contains', 'between'
      - value: depends on operator
    """
    if not filters:
        return df

    out = df.copy()

    for f in filters:
        col = f.get("column")
        op = f.get("operator")
        val = f.get("value")

        if not col or col not in out.columns or op is None:
            # skip invalid filters silently
            continue

        # in: value is list
        if op == "in":
            if isinstance(val, list):
                out = out[out[col].isin(val)]
        # equals: scalar
        elif op == "equals":
            out = out[out[col] == val]
        # contains: scalar substring, case-insensitive
        elif op == "contains":
            if isinstance(out[col].dtype, pd.StringDtype) or out[col].dtype == "object":
                s = out[col].astype(str)
                out = out[s.str.contains(str(val), case=False, na=False)]
        # between: two endpoints for dates / comparable values
        elif op == "between":
            if isinstance(val, list) and len(val) == 2:
                start, end = val
                # Let pandas do comparison, assume dates already normalized if they are dates
                out = out[(out[col] >= start) & (out[col] <= end)]

    return out


# -------------------------------------------------
# EXPORT HELPERS
# -------------------------------------------------

def to_excel_bytes(df: pd.DataFrame, sheet_name="Filtered") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buf.seek(0)
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
