import io
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime, timedelta, date


# -------------------------------------------------
# SAFE HELPERS
# -------------------------------------------------

def safe_to_date(series):
    """
    Convert any column into pure datetime.date.
    Handles strings, timestamps, timezone formats.
    """
    s = pd.to_datetime(series, errors="coerce")
    return s.dt.date


def pick_first_existing(df: pd.DataFrame, *names, default=None):
    """Utility: return first existing column name."""
    for n in names:
        if n and n in df.columns:
            return n
    return default


# -------------------------------------------------
# FILE LOADING
# -------------------------------------------------

def load_dataset(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        try:
            return pd.read_csv(uploaded_file, encoding="utf-8", engine="python")
        except Exception:
            return pd.read_csv(uploaded_file, encoding="latin1", engine="python")

    if name.endswith(".xlsx") or name.endswith(".xls"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, engine="openpyxl")

    raise ValueError("Unsupported file type. Upload CSV/XLSX only.")


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
            "example_values": [str(v) for v in ser.dropna().unique()[:10]],
        })

    return eda


# -------------------------------------------------
# NORMALIZATION: SET-ASIDE
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
            "vosb", "veteran owned small business",
            "veteran-owned small business"
        ],
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [
            "edwosb", "economically disadvantaged wosb",
            "economically disadvantaged women-owned"
        ],
        "NO SET-ASIDE": ["no set-aside used", "none", "unrestricted"],
    }


def normalize_set_aside_column(df, col, ai_patterns=None, new="Normalized_Set_Aside"):
    if col not in df.columns:
        df[new] = pd.NA
        return df

    base = _fallback_set_aside_patterns()
    ai_patterns = ai_patterns or {}

    # merge AI patterns
    for bucket, items in ai_patterns.items():
        if items:
            bucket = bucket.strip()
            base.setdefault(bucket, []).extend(items)

    lower_series = df[col].astype(str).str.lower().fillna("")

    def classify(v):
        v = v.strip().lower()
        if v in ("", "none", "null", "n/a", "na"):
            return None
        for bucket, pats in base.items():
            for p in pats:
                if p and p.lower() in v:
                    return bucket
        return "NO SET-ASIDE"

    df[new] = lower_series.apply(classify)
    return df


# -------------------------------------------------
# NORMALIZATION: OPPORTUNITY TYPE
# -------------------------------------------------

def _fallback_opp_patterns():
    return {
        "Solicitation": ["solicitation", "combined synopsis/solicitation"],
        "Presolicitation": ["presolicitation"],
        "Sources Sought": ["sources sought", "rfi", "request for information"],
    }


def normalize_opportunity_type_column(df, col, ai_patterns=None, new="Normalized_Opportunity_Type"):
    if col not in df.columns:
        df[new] = "Other"
        return df

    patterns = _fallback_opp_patterns()
    ai_patterns = ai_patterns or {}

    for bucket, items in ai_patterns.items():
        if items:
            bucket = bucket.strip()
            patterns.setdefault(bucket, []).extend(items)

    lower = df[col].astype(str).str.lower().fillna("")

    def classify(v):
        v = v.strip().lower()
        for bucket, pats in patterns.items():
            for p in pats:
                if p and p.lower() in v:
                    return bucket
        return "Other"

    df[new] = lower.apply(classify)
    return df


# -------------------------------------------------
# FINAL TABLE BUILDER
# -------------------------------------------------

def build_final_output_table(df, column_map, drop_no_set_aside=True):
    tmp = df.copy()

    if drop_no_set_aside and "Normalized_Set_Aside" in tmp.columns:
        tmp = tmp[tmp["Normalized_Set_Aside"].notna()]
        tmp = tmp[tmp["Normalized_Set_Aside"] != "NO SET-ASIDE"]

    # Resolve raw inputs
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

    ui = column_map.get("uilink") or pick_first_existing(tmp, "UiLink", "UIlink", "Ui URL")

    final = pd.DataFrame()

    if sol_num in tmp.columns:
        final["Solicitation Number"] = tmp[sol_num]

    if title in tmp.columns:
        final["Title"] = tmp[title]

    if agency in tmp.columns:
        final["Agency"] = tmp[agency]

    if sol_date in tmp.columns:
        final["Solicitation Date"] = safe_to_date(tmp[sol_date])

    if due_date in tmp.columns:
        final["Due Date"] = safe_to_date(tmp[due_date])

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
        final["_ord"] = cat
        if "Solicitation Date" in final.columns:
            final = final.sort_values(["_ord", "Solicitation Date"])
        else:
            final = final.sort_values(["_ord"])
        final = final.drop(columns=["_ord"])

    return final


# -------------------------------------------------
# FILTER ENGINE (FINAL VERSION)
# -------------------------------------------------

def apply_filters(df: pd.DataFrame, filters: List[Dict]) -> pd.DataFrame:
    """
    Apply LLM-generated filters to the table.
    Supports: in, equals, contains, between, next_days.
    FIXES date comparison errors permanently.
    """
    if not filters:
        return df

    out = df.copy()

    for f in filters:
        col = f.get("column")
        op = f.get("operator")
        val = f.get("value")

        if col not in out.columns:
            continue

        # Always normalize column to datetime.date if possible
        try:
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
        except:
            pass

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

        # BETWEEN (dates)
        if op == "between":
            try:
                d1 = pd.to_datetime(val[0], errors="coerce").date()
                d2 = pd.to_datetime(val[1], errors="coerce").date()
            except:
                continue

            out = out.dropna(subset=[col])
            out = out[(out[col] >= d1) & (out[col] <= d2)]
            continue

        # NEXT DAYS
        if op == "next_days":
            try:
                nd = int(val)
            except:
                continue

            today = date.today()
            future = today + timedelta(days=nd)

            out = out.dropna(subset=[col])
            out = out[(out[col] >= today) & (out[col] <= future)]
            continue

    return out


# -------------------------------------------------
# EXPORT HELPERS
# -------------------------------------------------

def to_excel_bytes(df, sheet_name="Filtered"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet_name[:31])
    buf.seek(0)
    return buf.getvalue()


def to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")
