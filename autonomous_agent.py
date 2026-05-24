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

from agent_state import get_state, is_file_seen, mark_file_seen
from data_engine import (
    build_final_output_table,
    build_full_eda,
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
from llm_agent import create_llm_plan

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

# Set-aside categories that qualify (SDVOSB, SDVOSBC, SBA-related)
QUALIFYING_SET_ASIDES = {
    "SDVOSB",
    "SDVOSBС",  # Cyrillic С variant
    "TOTAL SMALL BUSINESS SET ASIDE",
    "VETERAN OWNED SMALL BUSINESS (VOSB)",
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

    eda = build_full_eda(df)

    request = (
        "Filter SDVOSB, SDVOSBC, and SBA solicitations due within the next 14 days. "
        "Map all relevant columns including solicitation number, title, agency, "
        "solicitation date, due date, opportunity type, set-aside, and UI link."
    )
    plan = create_llm_plan(eda, request)
    column_map = plan.get("columns", {})
    set_aside_patterns = plan.get("set_aside_patterns", {})
    opp_type_patterns = plan.get("opportunity_type_patterns", {})

    set_aside_col = column_map.get("set_aside_column", "")
    opp_type_col = column_map.get("opportunity_type_column", "")

    df = normalize_set_aside_column(df, set_aside_col, set_aside_patterns, new_col="Normalized_Set_Aside")
    df = normalize_opportunity_type_column(df, opp_type_col, opp_type_patterns, new_col="Normalized_Opportunity_Type")

    final = build_final_output_table(df, column_map, drop_no_set_aside=False)

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
    Main pipeline entry point.
    Returns a summary dict with results.
    """
    summary = {
        "files_checked": 0,
        "files_processed": 0,
        "total_rows_added": 0,
        "errors": [],
        "processed_files": [],
    }

    try:
        if progress_callback:
            progress_callback("Scanning Google Drive folder...")

        files = list_drive_files(DRIVE_FOLDER_ID)
        summary["files_checked"] = len(files)
        log.info(f"Found {len(files)} files in Drive folder")

        new_files = [f for f in files if not is_file_seen(f["id"])]
        log.info(f"{len(new_files)} new (unprocessed) files")

        if not new_files:
            if progress_callback:
                progress_callback("No new files found.")
            return summary

        for f in new_files:
            file_id = f["id"]
            file_name = f["name"]

            if not file_name.lower().endswith((".csv", ".xlsx", ".xls")):
                log.info(f"  Skipping non-spreadsheet: {file_name}")
                mark_file_seen(file_id, file_name, 0, status="skipped")
                continue

            if progress_callback:
                progress_callback(f"Processing: {file_name}")

            try:
                rows_added, msg = process_file(file_id, file_name)
                mark_file_seen(file_id, file_name, rows_added, status="ok")
                summary["files_processed"] += 1
                summary["total_rows_added"] += rows_added
                summary["processed_files"].append({
                    "name": file_name,
                    "rows_added": rows_added,
                    "message": msg,
                })
                log.info(f"  Done: {msg}")
            except Exception as e:
                err = f"{file_name}: {e}"
                log.error(f"  Error: {err}\n{traceback.format_exc()}")
                mark_file_seen(file_id, file_name, 0, status="error", error=str(e))
                summary["errors"].append(err)

    except Exception as e:
        summary["errors"].append(f"Pipeline error: {e}")
        log.error(traceback.format_exc())

    return summary
