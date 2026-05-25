"""
Autonomous pipeline:
Every 5 hours (or on manual trigger):
  1. Scan Google Drive folder for new files not yet processed.
  2. Download each new file, run EDA + LLM column mapping.
  3. Normalize set-aside and opportunity type columns.
  4. Apply fixed filter: SDVOSB / SDVOSBC / SBA solicitations due within next 14 days.
  5. Deduplicate against existing sheet rows.
  6. Append new rows to the master xlsx on Drive (download → append → re-upload).
"""

import io
import logging
import os
import traceback
from datetime import datetime, timedelta

import pandas as pd

from agent_state import get_state, is_file_seen, mark_file_seen, get_last_processed_file_id
from data_engine import (
    build_final_output_table,
    force_date,
    normalize_opportunity_type_column,
    normalize_set_aside_column,
)
from google_connector import (
    append_rows_to_xlsx,
    download_drive_file,
    get_existing_solicitation_numbers,
    list_drive_files,
)
from llm_agent import classify_set_aside_descriptions

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1bSGpFbEW09jAq6pdn1i_WO8RUAa3DPUJ")

OUTPUT_COLUMNS = [
    "Solicitation Number",
    "Title",
    "Agency",
    "Solicitation Date",
    "Due Date",
    "Opportunity Type",
    "Normalized Set Aside",
    "UiLink",
    "Progress Report",
    "Award Date",
]

# Set-aside categories that qualify.
# These must exactly match the bucket keys produced by normalize_set_aside_column()
# in data_engine.py so nothing slips through.
QUALIFYING_SET_ASIDES = {
    "SDVOSB",                        # service-disabled / sdvosb / sdvosbc (substring match)
    "TOTAL SMALL BUSINESS SET ASIDE", # total small business / 100% small business
    "VETERAN OWNED SMALL BUSINESS (VOSB)",  # vosb / veteran
    "SBA Certified Economically Disadvantaged WOSB (EDWOSB) Program Set-Aside (FAR 19.15)",
}


def _load_file_bytes(file_id: str, file_name: str) -> pd.DataFrame:
    raw = download_drive_file(file_id)
    name_lower = file_name.lower()
    if name_lower.endswith(".csv"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding="utf-8")
        except Exception:
            return pd.read_csv(io.BytesIO(raw), encoding="latin1")
    elif name_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw), engine="openpyxl")
    else:
        raise ValueError(f"Unsupported file type: {file_name}")


def _apply_autonomous_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Filter: qualifying set-asides AND due within next 14 days."""
    out = df.copy()

    # Set-aside filter
    if "Normalized Set Aside" in out.columns:
        out = out[out["Normalized Set Aside"].isin(QUALIFYING_SET_ASIDES)]

    # Due date filter: today → today + 14 days
    if "Due Date" in out.columns:
        out["Due Date"] = force_date(out["Due Date"])
        today = datetime.utcnow().date()
        future = today + timedelta(days=14)
        out = out.dropna(subset=["Due Date"])
        out = out[(out["Due Date"] >= today) & (out["Due Date"] <= future)]

    return out


def _normalize_set_aside_three_tier(df: pd.DataFrame) -> pd.DataFrame:
    """
    Three-tier set-aside normalization:
      Tier 1 — TypeOfSetAside short code  (fast, exact, e.g. 'SBA', 'SDVOSB')
      Tier 2 — TypeOfSetAsideDescription  (full text fallback, pattern match)
      Tier 3 — LLM                        (only for rows still unresolved)
    Result is stored in 'Normalized_Set_Aside'.
    """
    df = df.copy()

    # Tier 1: short code
    df = normalize_set_aside_column(df, "TypeOfSetAside", {}, new_col="Normalized_Set_Aside")

    # Find rows that Tier 1 didn't resolve (None or NO SET-ASIDE)
    unresolved_mask = df["Normalized_Set_Aside"].isna() | (df["Normalized_Set_Aside"] == "NO SET-ASIDE")
    unresolved_count = unresolved_mask.sum()

    if unresolved_count == 0 or "TypeOfSetAsideDescription" not in df.columns:
        return df

    log.info(f"  Tier 2: trying description for {unresolved_count} unresolved rows")

    # Tier 2: run pattern match on description column for unresolved rows
    df_tier2 = df[unresolved_mask].copy()
    df_tier2 = normalize_set_aside_column(
        df_tier2, "TypeOfSetAsideDescription", {}, new_col="_tier2"
    )
    # Apply Tier 2 result where it's better than Tier 1
    improved = df_tier2["_tier2"].notna() & (df_tier2["_tier2"] != "NO SET-ASIDE")
    df.loc[unresolved_mask & improved.reindex(df.index, fill_value=False), "Normalized_Set_Aside"] = \
        df_tier2.loc[improved, "_tier2"].values

    # Re-check what's still unresolved after Tier 2
    still_unresolved = df["Normalized_Set_Aside"].isna() | (df["Normalized_Set_Aside"] == "NO SET-ASIDE")
    still_count = still_unresolved.sum()

    if still_count == 0 or "TypeOfSetAsideDescription" not in df.columns:
        return df

    # Tier 3: LLM for anything still not resolved — batch unique descriptions
    unique_descs = (
        df.loc[still_unresolved, "TypeOfSetAsideDescription"]
        .fillna("").astype(str).str.strip()
        .replace("", None).dropna().unique().tolist()
    )
    if unique_descs:
        log.info(f"  Tier 3: LLM classifying {len(unique_descs)} unique descriptions")
        llm_map = classify_set_aside_descriptions(unique_descs)
        if llm_map:
            def apply_llm(row):
                if still_unresolved.loc[row.name]:
                    desc = str(row.get("TypeOfSetAsideDescription", "")).strip()
                    if desc in llm_map:
                        return llm_map[desc]
                return row["Normalized_Set_Aside"]
            df["Normalized_Set_Aside"] = df.apply(apply_llm, axis=1)

    return df


def _df_to_row_dicts(df: pd.DataFrame) -> list:
    """Convert DataFrame to list of dicts with OUTPUT_COLUMNS keys."""
    rows = []
    for _, row in df.iterrows():
        d = {}
        for col in OUTPUT_COLUMNS:
            val = row.get(col, "")
            if not isinstance(val, str) and pd.isna(val):
                val = ""
            d[col] = str(val) if val != "" else ""
        rows.append(d)
    return rows


def process_file(file_id: str, file_name: str) -> tuple:
    """Process a single Drive file. Returns (rows_added, status_message)."""
    log.info(f"Processing file: {file_name} ({file_id})")

    df = _load_file_bytes(file_id, file_name)
    log.info(f"  Loaded {len(df)} rows, {len(df.columns)} columns")

    # Hardcoded column mapping — exact names from the source CSV.
    # No LLM needed; this is reliable and fast.
    COLUMN_MAP = {
        "solicitation_number": "SolicitationNumber",
        "title":               "Title",
        "agency":              "FullParentPathName",
        "solicitation_date":   "PostedDate",
        "due_date":            "ResponseDeadLine",
        "set_aside_column":    "TypeOfSetAside",
        "opportunity_type_column": "Type",
        "uilink":              "UiLink",
    }

    # Three-tier set-aside normalization:
    # Tier 1 → TypeOfSetAside short code, Tier 2 → TypeOfSetAsideDescription text, Tier 3 → LLM
    df = _normalize_set_aside_three_tier(df)
    df = normalize_opportunity_type_column(df, "Type", {}, new_col="Normalized_Opportunity_Type")

    final = build_final_output_table(df, COLUMN_MAP, drop_no_set_aside=False)

    filtered = _apply_autonomous_filter(final)
    log.info(f"  After filter: {len(filtered)} qualifying rows")

    if filtered.empty:
        return 0, "No qualifying rows found"

    # Deduplicate against existing sheet
    existing_sol_nums = get_existing_solicitation_numbers()

    if "Solicitation Number" in filtered.columns:
        before = len(filtered)
        filtered = filtered[
            ~filtered["Solicitation Number"].astype(str).str.strip().isin(existing_sol_nums)
        ]
        dupes = before - len(filtered)
        if dupes:
            log.info(f"  Skipped {dupes} already-seen solicitations")

    if filtered.empty:
        return 0, "All rows already in sheet (no new data)"

    filtered = filtered.copy()
    filtered["Progress Report"] = ""
    filtered["Award Date"] = ""

    row_dicts = _df_to_row_dicts(filtered)
    rows_added = append_rows_to_xlsx(row_dicts, OUTPUT_COLUMNS)
    log.info(f"  Appended {rows_added} rows to master sheet")

    return rows_added, f"Added {rows_added} rows"


def run_pipeline(progress_callback=None) -> dict:
    """
    Main pipeline entry point — always checks only the latest file in Drive.

    Logic:
      1. Find the most recent CSV/xlsx in the Drive folder.
      2. If it's the same file that was last processed → "No new updates yet."
      3. If it's a new file → filter (set-aside + 14-day due date), deduplicate,
         append qualifying rows to the master sheet.
    """
    summary = {
        "files_checked": 0,
        "files_processed": 0,
        "total_rows_added": 0,
        "errors": [],
        "processed_files": [],
        "message": "",
    }

    try:
        if progress_callback:
            progress_callback("Checking Google Drive for the latest file...")

        all_files = list_drive_files(DRIVE_FOLDER_ID)
        summary["files_checked"] = len(all_files)

        # Find the most recent spreadsheet file (Drive returns newest first)
        latest = next(
            (f for f in all_files
             if f["name"].lower().endswith((".csv", ".xlsx", ".xls"))),
            None,
        )

        if not latest:
            summary["message"] = "No spreadsheet files found in Drive folder."
            log.info(summary["message"])
            if progress_callback:
                progress_callback(summary["message"])
            return summary

        latest_id = latest["id"]
        latest_name = latest["name"]
        log.info(f"Latest file in Drive: {latest_name}")

        # Compare to the last file we processed
        last_processed_id = get_last_processed_file_id()
        if last_processed_id and last_processed_id == latest_id:
            summary["message"] = f"No new updates yet — latest file ({latest_name}) was already processed."
            log.info(summary["message"])
            if progress_callback:
                progress_callback(summary["message"])
            return summary

        # New file found — process it
        if progress_callback:
            progress_callback(f"New file found: {latest_name} — processing...")

        rows_added, msg = process_file(latest_id, latest_name)
        mark_file_seen(latest_id, latest_name, rows_added, status="ok")
        summary["files_processed"] = 1
        summary["total_rows_added"] = rows_added
        summary["processed_files"].append({
            "name": latest_name,
            "rows_added": rows_added,
            "message": msg,
        })
        summary["message"] = msg
        log.info(f"Done: {msg}")

    except Exception as e:
        summary["errors"].append(f"Pipeline error: {e}")
        summary["message"] = f"Error: {e}"
        log.error(traceback.format_exc())

    return summary
