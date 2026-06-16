"""
Autonomous pipeline v2 — clean slate.

FIRST RUN:
  - Processes ALL files in Drive folder, oldest → newest
  - Records every file ID processed

SUBSEQUENT RUNS:
  - Finds latest file
  - Skips any file already processed
  - Only processes new files
"""

import io
import logging
import os
import traceback
from datetime import datetime, timedelta

import pandas as pd

from agent_state import (
    get_last_processed_file_id,
    get_processed_file_ids,
    mark_file_seen,
)
from data_engine import (
    build_final_output_table,
    force_date,
    normalize_opportunity_type_column,
    normalize_set_aside_column,
)
from google_connector import (
    append_rows_to_xlsx,
    download_drive_file,
    get_existing_dedup_keys,
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

QUALIFYING_SET_ASIDES = {
    "SDVOSB",                      # covers SDVOSB and SDVOSBC short codes
    "TOTAL SMALL BUSINESS SET ASIDE",  # covers SBA short code
}

COLUMN_MAP = {
    "solicitation_number":    "SolicitationNumber",
    "title":                  "Title",
    "agency":                 "FullParentPathName",
    "solicitation_date":      "PostedDate",
    "due_date":               "ResponseDeadLine",
    "set_aside_column":       "TypeOfSetAside",
    "opportunity_type_column":"Type",
    "uilink":                 "UiLink",
}


# ─────────────────────────────────────────────
# File loading
# ─────────────────────────────────────────────

def _load_df(file_id: str, file_name: str) -> pd.DataFrame:
    raw = download_drive_file(file_id)
    name = file_name.lower()
    if name.endswith(".csv"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding="utf-8")
        except Exception:
            return pd.read_csv(io.BytesIO(raw), encoding="latin1")
    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw), engine="openpyxl")
    raise ValueError(f"Unsupported file type: {file_name}")


# ─────────────────────────────────────────────
# Filtering
# ─────────────────────────────────────────────

def _apply_filter(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Normalized Set Aside" in out.columns:
        out = out[out["Normalized Set Aside"].isin(QUALIFYING_SET_ASIDES)]
    if "Due Date" in out.columns:
        out["Due Date"] = force_date(out["Due Date"])
        today  = datetime.utcnow().date()
        future = today + timedelta(days=14)
        out = out.dropna(subset=["Due Date"])
        out = out[(out["Due Date"] >= today) & (out["Due Date"] <= future)]
    return out


# ─────────────────────────────────────────────
# Set-aside normalization (3-tier)
# ─────────────────────────────────────────────

def _normalize_set_aside(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = normalize_set_aside_column(df, "TypeOfSetAside", {}, new_col="Normalized_Set_Aside")

    unresolved = df["Normalized_Set_Aside"].isna() | (df["Normalized_Set_Aside"] == "NO SET-ASIDE")
    if unresolved.sum() == 0 or "TypeOfSetAsideDescription" not in df.columns:
        return df

    log.info(f"  Tier 2: {unresolved.sum()} rows")
    df2 = normalize_set_aside_column(
        df[unresolved].copy(), "TypeOfSetAsideDescription", {}, new_col="_t2"
    )
    improved = df2["_t2"].notna() & (df2["_t2"] != "NO SET-ASIDE")
    df.loc[unresolved & improved.reindex(df.index, fill_value=False), "Normalized_Set_Aside"] = \
        df2.loc[improved, "_t2"]

    still = df["Normalized_Set_Aside"].isna() | (df["Normalized_Set_Aside"] == "NO SET-ASIDE")
    if still.sum() == 0:
        return df

    descs = (
        df.loc[still, "TypeOfSetAsideDescription"]
        .fillna("").astype(str).str.strip()
        .replace("", None).dropna().unique().tolist()
    )
    if descs:
        log.info(f"  Tier 3: LLM classifying {len(descs)} descriptions")
        llm_map = classify_set_aside_descriptions(descs)
        if llm_map:
            def _apply(row):
                if still.loc[row.name]:
                    desc = str(row.get("TypeOfSetAsideDescription", "")).strip()
                    return llm_map.get(desc, row["Normalized_Set_Aside"])
                return row["Normalized_Set_Aside"]
            df["Normalized_Set_Aside"] = df.apply(_apply, axis=1)
    return df


# ─────────────────────────────────────────────
# Process one file
# ─────────────────────────────────────────────

def process_file(file_id: str, file_name: str,
                 existing_sols: set, existing_links: set) -> tuple:
    """Process one file. Returns (rows_added, message)."""
    log.info(f"Processing: {file_name}")

    df = _load_df(file_id, file_name)
    log.info(f"  {len(df)} rows, {len(df.columns)} columns")

    df = _normalize_set_aside(df)
    df = normalize_opportunity_type_column(df, "Type", {}, new_col="Normalized_Opportunity_Type")

    final    = build_final_output_table(df, COLUMN_MAP, drop_no_set_aside=False)
    filtered = _apply_filter(final)
    log.info(f"  After filter: {len(filtered)} qualifying rows")

    if filtered.empty:
        return 0, "No qualifying rows after filtering"

    # Deduplicate against what's already in the sheet
    before = len(filtered)
    def _is_dupe(row):
        sol  = str(row.get("Solicitation Number", "")).strip()
        link = str(row.get("UiLink", "")).strip()
        if sol and sol != "nan":
            return sol in existing_sols
        if link and link != "nan":
            return link in existing_links
        return False

    filtered = filtered[~filtered.apply(_is_dupe, axis=1)].copy()
    dupes = before - len(filtered)
    if dupes:
        log.info(f"  Skipped {dupes} duplicates")

    if filtered.empty:
        return 0, "All rows already in sheet"

    filtered["Progress Report"] = ""
    filtered["Award Date"]      = ""

    rows = []
    for _, row in filtered.iterrows():
        d = {}
        for col in OUTPUT_COLUMNS:
            val = row.get(col, "")
            d[col] = "" if (not isinstance(val, str) and pd.isna(val)) else str(val)
        rows.append(d)

    # Add these to dedup sets so next file in same run doesn't re-add
    for r in rows:
        s = r.get("Solicitation Number", "").strip()
        l = r.get("UiLink", "").strip()
        if s and s != "nan":
            existing_sols.add(s)
        if l and l != "nan":
            existing_links.add(l)

    rows_added = append_rows_to_xlsx(rows, OUTPUT_COLUMNS)
    log.info(f"  ✅ Appended {rows_added} rows")
    return rows_added, f"Added {rows_added} rows"


# ─────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────

def run_pipeline(progress_callback=None) -> dict:
    """
    Main pipeline entry point.

    FIRST RUN  → processes ALL files oldest → newest.
    NEXT RUNS  → skips already-processed files, only processes new ones.
    """
    summary = {
        "files_checked":   0,
        "files_processed": 0,
        "total_rows_added":0,
        "errors":          [],
        "processed_files": [],
        "message":         "",
    }

    try:
        if progress_callback:
            progress_callback("Scanning Google Drive folder...")

        # Get all files — returned oldest first (orderBy: createdTime asc)
        all_files = list_drive_files(DRIVE_FOLDER_ID)
        # Filter to spreadsheet files only
        data_files = [f for f in all_files
                      if f["name"].lower().endswith((".csv", ".xlsx", ".xls"))]
        summary["files_checked"] = len(data_files)

        if not data_files:
            summary["message"] = "No CSV/Excel files found in Drive folder."
            if progress_callback:
                progress_callback(summary["message"])
            return summary

        # Which files have we already processed?
        processed_ids = get_processed_file_ids()
        new_files = [f for f in data_files if f["id"] not in processed_ids]

        if not new_files:
            latest_name = data_files[-1]["name"]   # newest
            summary["message"] = (
                f"No new files — latest file ({latest_name}) was already processed."
            )
            log.info(summary["message"])
            if progress_callback:
                progress_callback(summary["message"])
            return summary

        log.info(f"Found {len(new_files)} new file(s) to process "
                 f"(skipping {len(processed_ids)} already processed)")

        if progress_callback:
            progress_callback(
                f"Found {len(new_files)} new file(s) — processing oldest → newest…"
            )

        # Load existing dedup keys ONCE before processing all files
        existing_sols, existing_links = get_existing_dedup_keys()

        total_rows = 0
        for idx, f in enumerate(new_files, 1):
            fname = f["name"]
            fid   = f["id"]

            if progress_callback:
                progress_callback(f"Processing file {idx}/{len(new_files)}: {fname}")

            try:
                rows_added, msg = process_file(
                    fid, fname, existing_sols, existing_links
                )
                mark_file_seen(fid, fname, rows_added, status="ok")
                total_rows += rows_added
                summary["processed_files"].append({
                    "name": fname, "rows_added": rows_added, "message": msg
                })
                log.info(f"  [{idx}/{len(new_files)}] {fname} → {msg}")

            except Exception as e:
                err = f"Error processing {fname}: {e}"
                log.error(err)
                log.error(traceback.format_exc())
                summary["errors"].append(err)
                mark_file_seen(fid, fname, 0, status="error")

        summary["files_processed"]  = len(new_files)
        summary["total_rows_added"] = total_rows
        summary["message"] = (
            f"Processed {len(new_files)} file(s) — {total_rows} rows added."
        )
        log.info(summary["message"])

    except Exception as e:
        summary["errors"].append(f"Pipeline error: {e}")
        summary["message"] = f"Error: {e}"
        log.error(traceback.format_exc())

    return summary
