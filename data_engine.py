import io
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime, timedelta, date
import pytz


# -------------------------------------------------
# UNIVERSAL SAFE DATE CONVERTER
# -------------------------------------------------
def force_date(series: pd.Series) -> pd.Series:
    """
    Convert ANY series into datetime.date values.
    NEVER raises .dt errors.
    """
    try:
        # First attempt — pandas conversion
        s = pd.to_datetime(series, errors="coerce")
        return s.dt.date
    except Exception:
        # Absolute fallback — convert cell-by-cell
        def safe(val):
            try:
                return pd.to_datetime(val, errors="coerce").date()
            except:
                return None
        return series.apply(safe)


# -------------------------------------------------
# COLUMN PICKER
# -------------------------------------------------
def pick_first_existing(df: pd.DataFrame, *names, default=None):
    for name in names:
        if name and name in df.columns:
            return name
    return default


# -------------------------------------------------
# LOAD DATASET
# -------------------------------------------------
def load_dataset(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        try:
            return pd.read_csv(uploaded_file, encoding="utf-8")
        except:
            return pd.read_csv(uploaded_file, encoding="latin1")

    if name.endswith(".xlsx") or name.endswith(".xls"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, engine="openpyxl")

    raise ValueError("Unsupported file type")


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
# NORMALIZATION: SET-ASIDE
# -------------------------------------------------
def _fallback_set_aside_patterns():
    return {
        "SDVOSB": ["sdvosb", "service-disabled", "service disabled"],
        "WOSB": ["wosb", "women"],
        "TOTAL SMALL BUSINESS SET ASIDE": ["total small business", "100% small business"],
        "VETERAN OWNED SMALL BUSINESS (VOSB)": ["vosb", "veteran"],
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [
            "edwosb", "economically disadvantaged"
        ],
        "NO SET-ASIDE": ["no set aside", "none", "unrestricted"]
    }


def normalize_set_aside_column(df, col, ai_patterns=None, new_col="Normalized_Set_Aside"):
    if col not in df.columns:
        df[new_col] = pd.NA
        return df

    base = _fallback_set_aside_patterns()
    ai_patterns = ai_patterns or {}

    for bucket, list_p in ai_patterns.items():
        if list_p:
            base.setdefault(bucket.strip(), []).extend(list_p)

    lowered = df[col].astype(str).str.lower()

    def classify(v):
        v = v.strip().lower()
        if v in ("", "none", "null", "n/a"):
            return None
        for bucket, pats in base.items():
            for p in pats:
                if p.lower() in v:
                    return bucket
        return "NO SET-ASIDE"

    df[new_col] = lowered.apply(classify)
    return df


# -------------------------------------------------
# NORMALIZATION: OPPORTUNITY TYPE
# -------------------------------------------------
def _fallback_opp_patterns():
    return {
        "Solicitation": ["solicitation", "combined synopsis"],
        "Presolicitation": ["presolicitation"],
        "Sources Sought": ["sources sought", "rfi", "request for information"]
    }


def normalize_opportunity_type_column(df, col, ai_patterns=None, new_col="Normalized_Opportunity_Type"):
    if col not in df.columns:
        df[new_col] = "Other"
        return df

    patterns = _fallback_opp_patterns()
    ai_patterns = ai_patterns or {}

    for bucket, patlist in ai_patterns.items():
        if patlist:
            patterns.setdefault(bucket.strip(), []).extend(patlist)

    lowered = df[col].astype(str).str.lower()

    def classify(v):
        v = v.strip().lower()
        for bucket, pats in patterns.items():
            for p in pats:
                if p.lower() in v:
                    return bucket
        return "Other"

    df[new_col] = lowered.apply(classify)
    return df


# -------------------------------------------------
# FINAL OUTPUT TABLE
# -------------------------------------------------
def build_final_output_table(df: pd.DataFrame, column_map: Dict, drop_no_set_aside=True):
    tmp = df.copy()

    # Drop unwanted set-asides
    if drop_no_set_aside and "Normalized_Set_Aside" in tmp.columns:
        tmp = tmp[tmp["Normalized_Set_Aside"].notna()]
        tmp = tmp[tmp["Normalized_Set_Aside"] != "NO SET-ASIDE"]

    # Column resolution
    sol_num = column_map.get("solicitation_number") or pick_first_existing(
        tmp, "SolicitationNumber", "NoticeId", "NoticeID"
    )
    title = column_map.get("title") or pick_first_existing(tmp, "Title", "Description")
    agency = column_map.get("agency") or pick_first_existing(tmp, "Agency", "Office")

    sol_date = column_map.get("solicitation_date") or pick_first_existing(
        tmp, "PostedDate", "NoticeDate", "SolicitationDate"
    )

    # Validate allowed solicitation date columns
    if sol_date not in [None, "", "PostedDate", "NoticeDate", "SolicitationDate"]:
        raise ValueError(f"Invalid solicitation_date column chosen: {sol_date}")

    due_date = column_map.get("due_date") or pick_first_existing(
        tmp, "ResponseDeadLine", "ResponseDate", "DueDate"
    )

    # Validate allowed due date columns
    if due_date not in [None, "", "ResponseDeadLine", "ResponseDate", "DueDate"]:
        raise ValueError(f"Invalid due_date column chosen: {due_date}")

    uilink = column_map.get("uilink") or pick_first_existing(
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
        final["Solicitation Date"] = force_date(tmp[sol_date])

    if due_date in tmp.columns:
        final["Due Date"] = force_date(tmp[due_date])

    if "Normalized_Opportunity_Type" in tmp.columns:
        final["Opportunity Type"] = tmp["Normalized_Opportunity_Type"]

    if "Normalized_Set_Aside" in tmp.columns:
        final["Normalized Set Aside"] = tmp["Normalized_Set_Aside"]

    if uilink in tmp.columns:
        final["UiLink"] = tmp[uilink]

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
# FILTERS (ALL date math done here)
# -------------------------------------------------
def lagos_today():
    return datetime.now(pytz.timezone("Africa/Lagos")).date()


def get_last_week_range():
    today = lagos_today()
    monday_this = today - timedelta(days=today.weekday())
    monday_last = monday_this - timedelta(days=7)
    return monday_last, monday_last + timedelta(days=6)


def get_this_week_range():
    today = lagos_today()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def apply_filters(df: pd.DataFrame, filters: List[Dict]) -> pd.DataFrame:
    if not filters:
        return df

    out = df.copy()

    for f in filters:
        col = f.get("column")
        op = f.get("operator")
        val = f.get("value")

        if not col or col not in out.columns:
            continue

        # Always normalize date fields
        if col in ["Due Date", "Solicitation Date"]:
            out[col] = force_date(out[col])

        # ---- IN ----
        if op == "in":
            out = out[out[col].isin(val)]
            continue

        # ---- EQUALS ----
        if op == "equals":
            out = out[out[col] == val]
            continue

        # ---- CONTAINS ----
        if op == "contains":
            s = out[col].astype(str)
            out = out[s.str.contains(str(val), case=False, na=False)]
            continue

        # ---- BETWEEN ----
        if op == "between":
            try:
                d1 = pd.to_datetime(val[0], errors="coerce").date()
                d2 = pd.to_datetime(val[1], errors="coerce").date()
            except:
                continue
            out = out.dropna(subset=[col])
            out = out[(out[col] >= d1) & (out[col] <= d2)]
            continue

        # ---- next_days ----
        if op == "next_days":
            today = lagos_today()
            future = today + timedelta(days=int(val))
            out = out.dropna(subset=[col])
            out = out[(out[col] >= today) & (out[col] <= future)]
            continue

        # ---- today ----
        if op == "today":
            t = lagos_today()
            out = out.dropna(subset=[col])
            out = out[out[col] == t]
            continue

        # ---- tomorrow ----
        if op == "tomorrow":
            t = lagos_today() + timedelta(days=1)
            out = out.dropna(subset=[col])
            out = out[out[col] == t]
            continue

        # ---- yesterday ----
        if op == "yesterday":
            t = lagos_today() - timedelta(days=1)
            out = out.dropna(subset=[col])
            out = out[out[col] == t]
            continue

        # ---- this_week ----
        if op == "this_week":
            start, end = get_this_week_range()
            out = out.dropna(subset=[col])
            out = out[(out[col] >= start) & (out[col] <= end)]
            continue

        # ---- last_week ----
        if op == "last_week":
            start, end = get_last_week_range()
            out = out.dropna(subset=[col])
            out = out[(out[col] >= start) & (out[col] <= end)]
            continue

        # ---- last_7_days ----
        if op == "last_7_days":
            today = lagos_today()
            start = today - timedelta(days=7)
            out = out.dropna(subset=[col])
            out = out[(out[col] >= start) & (out[col] <= today)]
            continue

    return out


# -------------------------------------------------
# EXPORTS
# -------------------------------------------------
def to_excel_bytes(df: pd.DataFrame, sheet_name="Filtered") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buf.seek(0)
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
