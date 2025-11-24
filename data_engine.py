# data_engine.py
import pandas as pd
from typing import Dict, Any


def load_dataset(uploaded_file) -> pd.DataFrame:
    """Load XLSX/XLS/CSV into a pandas DataFrame."""
    fname = uploaded_file.name.lower()
    if fname.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    elif fname.endswith(".xlsx") or fname.endswith(".xls"):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("Unsupported file type. Please upload CSV or Excel.")
    return df


def build_full_eda(df: pd.DataFrame, max_unique: int = 20, sample_rows: int = 10) -> Dict[str, Any]:
    """
    Build a full EDA summary for the LLM:
    - shape
    - dtypes
    - per-column unique values (capped)
    - missing counts
    - basic numeric stats
    - inferred role candidates (date, type, set-aside, naics)
    - sample rows
    """
    eda: Dict[str, Any] = {}

    # Shape
    eda["shape"] = {"rows": int(df.shape[0]), "columns": int(df.shape[1])}
    eda["columns"] = list(df.columns)
    eda["dtypes"] = {col: str(dtype) for col, dtype in df.dtypes.items()}

    # Missing counts
    eda["missing_counts"] = df.isna().sum().to_dict()

    # Sample rows
    eda["sample_rows"] = df.head(sample_rows).to_dict(orient="records")

    # Unique values
    unique_values = {}
    for col in df.columns:
        try:
            uniques = df[col].dropna().astype(str).unique()[:max_unique]
            unique_values[col] = list(uniques)
        except Exception:
            unique_values[col] = []
    eda["unique_values"] = unique_values

    # Basic numeric stats
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    stats = {}
    for col in numeric_cols:
        desc = df[col].describe()
        stats[col] = {
            "count": float(desc.get("count", 0)),
            "mean": float(desc.get("mean", 0)),
            "std": float(desc.get("std", 0)),
            "min": float(desc.get("min", 0)),
            "max": float(desc.get("max", 0)),
        }
    eda["numeric_stats"] = stats

    # Infer candidate roles based on column names + unique values
    date_candidates = []
    type_candidates = []
    set_aside_candidates = []
    naics_candidates = []

    for col in df.columns:
        cl = col.lower()
        if any(k in cl for k in ["date", "deadline", "posted", "response", "close", "closing"]):
            date_candidates.append(col)

        if any(k in cl for k in ["type", "base type", "notice type"]):
            type_candidates.append(col)

        if any(k in cl for k in ["setaside", "set-aside", "set_aside"]):
            set_aside_candidates.append(col)

        if any(k in cl for k in ["naics"]):
            naics_candidates.append(col)

        # also inspect unique values for hints
        uvals = [u.lower() for u in unique_values.get(col, [])]
        if any("sdvosb" in u or "wosb" in u or "small business" in u for u in uvals):
            if col not in set_aside_candidates:
                set_aside_candidates.append(col)

        if any("solicitation" in u or "sources sought" in u or "award notice" in u for u in uvals):
            if col not in type_candidates:
                type_candidates.append(col)

        if all(len(u) == 6 and u.isdigit() for u in uvals[:5] or []):
            if col not in naics_candidates:
                naics_candidates.append(col)

    eda["candidate_roles"] = {
        "date_columns": date_candidates,
        "type_columns": type_candidates,
        "set_aside_columns": set_aside_candidates,
        "naics_columns": naics_candidates,
    }

    return eda
