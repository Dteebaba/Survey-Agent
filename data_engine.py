# data_engine.py
import io
from typing import Dict, List, Optional

import pandas as pd


# ---------- FILE LOADING ----------

def load_dataset(uploaded_file) -> pd.DataFrame:
    """
    Robust loader for CSV, XLSX, XLS.
    """
    fname = uploaded_file.name.lower()

    if fname.endswith(".csv"):
        try:
            return pd.read_csv(uploaded_file, encoding="utf-8", engine="python")
        except Exception:
            return pd.read_csv(uploaded_file, encoding="latin1", engine="python")

    elif fname.endswith(".xlsx") or fname.endswith(".xls"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, engine="openpyxl")

    else:
        raise ValueError("Unsupported file type. Please upload CSV or Excel (.xlsx/.xls).")


# ---------- EDA BUILDER ----------

def build_full_eda(df: pd.DataFrame) -> Dict:
    """
    Build a compact EDA summary to send to the LLM.
    """
    eda = {
        "columns": [],
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
    }

    for col in df.columns:
        series = df[col]
        col_info = {
            "name": col,
            "dtype": str(series.dtype),
            "non_null_count": int(series.notna().sum()),
            "example_values": [str(v) for v in series.dropna().unique()[:10]],
        }
        eda["columns"].append(col_info)

    return eda


# ---------- SET-ASIDE NORMALIZATION ----------

SET_ASIDE_BUCKETS = [
    "SDVOSB",
    "WOSB",
    "TOTAL SMALL BUSINESS SET ASIDE",
    "VETERAN OWNED SMALL BUSINESS (VOSB)",
    "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)",
    "NO SET-ASIDE",
]


def _fallback_set_aside_patterns() -> Dict[str, List[str]]:
    return {
        "SDVOSB": [
            "sdvosb",
            "service-disabled veteran-owned",
            "service disabled veteran owned",
            "service-disabled veteran owned",
        ],
        "WOSB": [
            "wosb",
            "women-owned small business",
            "women owned small business",
            "women owned sb",
            "women-owned sb",
        ],
        "TOTAL SMALL BUSINESS SET ASIDE": [
            "total small business",
            "100% small business",
            "small business set-aside",
            "small business set aside",
            "total sb",
        ],
        "VETERAN OWNED SMALL BUSINESS (VOSB)": [
            "vosb",
            "veteran owned small business",
            "veteran-owned small business",
            "veteran owned sb",
            "veteran-owned sb",
        ],
        "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)": [
            "edwosb",
            "economically disadvantaged women-owned",
            "economically disadvantaged wosb",
        ],
        "NO SET-ASIDE": [
            "no set-aside used",
            "no set aside used",
            "none",
            "unrestricted",
        ],
    }


def normalize_set_aside_column(
    df: pd.DataFrame,
    set_aside_col: str,
    ai_patterns: Optional[Dict[str, List[str]]] = None,
    new_col_name: str = "Normalized_Set_Aside",
) -> pd.DataFrame:
    """
    Create a new column with normalized set-aside values.
    Uses AI patterns (from llm_agent plan) plus safe hard-coded fallbacks.
    """
    if set_aside_col not in df.columns:
        df[new_col_name] = pd.NA
        return df

    patterns = _fallback_set_aside_patterns()
    ai_patterns = ai_patterns or {}

    for bucket, ai_list in ai_patterns.items():
        if not ai_list:
            continue
        bucket_key = bucket.strip()
        if bucket_key not in patterns:
            patterns[bucket_key] = []
        patterns[bucket_key].extend(ai_list)

    col = df[set_aside_col].astype(str).str.lower().fillna("")

    def classify(value: str):
        v = value.strip().lower()
        if v == "" or v in {"none", "n/a", "na", "null"}:
            return None
        for bucket, pats in patterns.items():
            for p in pats:
                if p and p.lower() in v:
                    return bucket
        return "NO SET-ASIDE"

    df[new_col_name] = col.apply(classify)
    return df


# ---------- OPPORTUNITY TYPE NORMALIZATION ----------

OPP_TYPE_ORDER = ["Solicitation", "Presolicitation", "Sources Sought", "Other"]


def _fallback_opp_type_patterns() -> Dict[str, List[str]]:
    return {
        "Solicitation": [
            "solicitation",
            "combined synopsis/solicitation",
            "combined synopsis / solicitation",
        ],
        "Presolicitation": [
            "presolicitation",
        ],
        "Sources Sought": [
            "sources sought",
            "rfi",
            "request for information",
        ],
    }


def normalize_opportunity_type_column(
    df: pd.DataFrame,
    type_col: str,
    ai_patterns: Optional[Dict[str, List[str]]] = None,
    new_col_name: str = "Normalized_Opportunity_Type",
) -> pd.DataFrame:
    if type_col not in df.columns:
        df[new_col_name] = "Other"
        return df

    patterns = _fallback_opp_type_patterns()
    ai_patterns = ai_patterns or {}
    for bucket, ai_list in ai_patterns.items():
        if not ai_list:
            continue
        bucket_key = bucket.strip()
        if bucket_key not in patterns:
            patterns[bucket_key] = []
        patterns[bucket_key].extend(ai_list)

    col = df[type_col].astype(str).str.lower().fillna("")

    def classify(value: str) -> str:
        v = value.strip().lower()
        for bucket, pats in patterns.items():
            for p in pats:
                if p and p.lower() in v:
                    return bucket
        return "Other"

    df[new_col_name] = col.apply(classify)
    return df


# ---------- FINAL OUTPUT TABLE ----------

def build_final_output_table(
    df: pd.DataFrame,
    column_map: Dict[str, str],
    drop_no_set_aside: bool = True,
) -> pd.DataFrame:
    """
    Final table with exactly:
      - Solicitation Number
      - Title
      - Agency
      - Solicitation Date
      - Opportunity Type
      - Normalized Set Aside
      - Due Date
      - UiLink
    """

    def choose_col(keys, default=None):
        for k in keys:
            if k in df.columns:
                return k
        return default

    sol_num_col = column_map.get("solicitation_number") or choose_col(
        ["SolicitationNumber", "NoticeId", "NoticeID", "Solicitation_Number"]
    )
    title_col = column_map.get("title") or choose_col(["Title", "Description"])
    agency_col = column_map.get("agency") or choose_col(["Agency", "Office", "Agency/Office"])
    sol_date_col = column_map.get("solicitation_date") or choose_col(
        ["PostedDate", "NoticeDate", "SolicitationDate"]
    )
    due_date_col = column_map.get("due_date") or choose_col(
        ["ResponseDeadLine", "DueDate", "ResponseDate"]
    )
    uilink_col = column_map.get("uilink") or choose_col(["UiLink", "UIlink", "Ui URL"])

    norm_type_col = "Normalized_Opportunity_Type"
    norm_set_aside_col = "Normalized_Set_Aside"

    tmp = df.copy()
    if drop_no_set_aside and norm_set_aside_col in tmp.columns:
        tmp = tmp[tmp[norm_set_aside_col].notna()]
        tmp = tmp[tmp[norm_set_aside_col] != "NO SET-ASIDE"]

    final_df = pd.DataFrame()

    if sol_num_col in tmp.columns:
        final_df["Solicitation Number"] = tmp[sol_num_col]
    if title_col in tmp.columns:
        final_df["Title"] = tmp[title_col]
    if agency_col in tmp.columns:
        final_df["Agency"] = tmp[agency_col]
    if sol_date_col in tmp.columns:
        final_df["Solicitation Date"] = pd.to_datetime(
            tmp[sol_date_col], errors="coerce"
        ).dt.date
    if norm_type_col in tmp.columns:
        final_df["Opportunity Type"] = tmp[norm_type_col]
    if norm_set_aside_col in tmp.columns:
        final_df["Normalized Set Aside"] = tmp[norm_set_aside_col]
    if due_date_col and due_date_col in tmp.columns:
        final_df["Due Date"] = pd.to_datetime(
            tmp[due_date_col], errors="coerce"
        ).dt.date
    if uilink_col and uilink_col in tmp.columns:
        final_df["UiLink"] = tmp[uilink_col]

    if "Opportunity Type" in final_df.columns:
        type_cat = pd.Categorical(
            final_df["Opportunity Type"],
            categories=["Solicitation", "Presolicitation", "Sources Sought", "Other"],
            ordered=True,
        )
        final_df = final_df.assign(_type_order=type_cat)
        if "Solicitation Date" in final_df.columns:
            final_df = final_df.sort_values(by=["_type_order", "Solicitation Date"])
        else:
            final_df = final_df.sort_values(by=["_type_order"])
        final_df = final_df.drop(columns=["_type_order"])

    return final_df


# ---------- EXPORT HELPERS ----------

def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Filtered") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buf.seek(0)
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
