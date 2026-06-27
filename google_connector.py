"""
Google Drive and Sheets connector v2.
Fresh sheet. On first run processes ALL files oldest→newest.
On subsequent runs skips already-processed files.
Uses GOOGLE_ACCESS_TOKEN from Replit Secrets.
"""
import io
import logging
import os
import requests
import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Font, PatternFill, Alignment

log = logging.getLogger(__name__)

SPREADSHEET_FILE_ID = os.getenv("GOOGLE_SHEETS_ID", "151jig9_3v-__dHfk7TksitJYONDMOLQV")
SHEET_TAB_NAME      = "Opportunities"
URGENT_TAB_NAME     = "Urgent"

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

PROGRESS_OPTIONS = (
    "Bid Submitted,Bid InProgress,Sub Contractor Inquiry,"
    "Bid Past Due Date,Bid Quote Requested"
)


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────

def _token() -> str:
    from token_store import get_token
    return get_token("google-drive")


def _headers(extra: dict = None) -> dict:
    h = {"Authorization": f"Bearer {_token()}"}
    if extra:
        h.update(extra)
    return h


# ─────────────────────────────────────────────
# Drive helpers
# ─────────────────────────────────────────────

def list_drive_files(folder_id: str) -> list:
    """List all CSV/xlsx files, oldest first."""
    resp = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "files(id,name,mimeType,modifiedTime,createdTime)",
            "orderBy": "createdTime asc",   # oldest first
            "pageSize": 200,
        },
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("files", [])


def download_drive_file(file_id: str) -> bytes:
    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media"},
        headers=_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


def upload_drive_file(file_id: str, content: bytes, mime_type: str) -> dict:
    resp = requests.patch(
        f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
        params={"uploadType": "media"},
        headers=_headers({"Content-Type": mime_type}),
        data=content,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────
# Sheet setup
# ─────────────────────────────────────────────

def _open_master() -> tuple:
    """Download master xlsx for writing. Returns (wb, ws, raw_bytes)."""
    raw = download_drive_file(SPREADSHEET_FILE_ID)
    wb  = openpyxl.load_workbook(io.BytesIO(raw))

    # Create fresh tab if it doesn't exist
    if SHEET_TAB_NAME not in wb.sheetnames:
        log.info(f"Creating new sheet tab: '{SHEET_TAB_NAME}'")
        ws = wb.create_sheet(SHEET_TAB_NAME)
        _write_headers(ws)
    else:
        ws = wb[SHEET_TAB_NAME]
        # If sheet exists but has no headers, write them
        if ws.max_row == 0 or ws.cell(1, 1).value is None:
            _write_headers(ws)

    return wb, ws, raw


def _open_master_readonly():
    """Download master xlsx in read-only mode (faster, no styles loaded)."""
    raw = download_drive_file(SPREADSHEET_FILE_ID)
    wb  = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws  = wb[SHEET_TAB_NAME] if SHEET_TAB_NAME in wb.sheetnames else wb.active
    return wb, ws


def _write_headers(ws):
    """Write bold headers to row 1."""
    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")

    for col_idx, col_name in enumerate(OUTPUT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font      = header_fill and header_font
        cell.fill      = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Set column widths
    widths = [20, 40, 35, 18, 18, 20, 35, 40, 20, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    log.info(f"Headers written to sheet '{ws.title}'")


def _save_and_upload(wb) -> None:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    upload_drive_file(
        SPREADSHEET_FILE_ID,
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    log.info("✅ Master sheet uploaded successfully")


# ─────────────────────────────────────────────
# Dedup keys
# ─────────────────────────────────────────────

def get_existing_dedup_keys() -> tuple:
    """Return (solicitation_numbers, uilinks) already in the sheet."""
    try:
        _, ws, _ = _open_master()
        headers  = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]

        def _find(name):
            for i, h in enumerate(headers):
                if h and str(h).strip().lower() == name.lower():
                    return i + 1
            return None

        sol_col  = _find("Solicitation Number")
        link_col = _find("UiLink")
        sol_nums, uilinks = set(), set()

        for row in range(2, ws.max_row + 1):
            if sol_col:
                v = ws.cell(row, sol_col).value
                if v:
                    sol_nums.add(str(v).strip())
            if link_col:
                v = ws.cell(row, link_col).value
                if v:
                    uilinks.add(str(v).strip())

        log.info(f"Existing dedup keys: {len(sol_nums)} sol#, {len(uilinks)} links")
        return sol_nums, uilinks
    except Exception as e:
        log.warning(f"Could not load dedup keys: {e}")
        return set(), set()


# Legacy wrapper
def get_existing_solicitation_numbers() -> set:
    s, _ = get_existing_dedup_keys()
    return s


# ─────────────────────────────────────────────
# Append rows
# ─────────────────────────────────────────────

def append_rows_to_xlsx(rows: list, output_columns: list) -> int:
    """Append rows to master sheet. Returns count appended."""
    if not rows:
        return 0

    wb, ws, _ = _open_master()

    # Build header map
    header_map = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(1, c).value
        if v:
            header_map[str(v).strip()] = c

    # Find true next empty row
    next_row = 2
    for r in range(ws.max_row, 1, -1):
        if any(ws.cell(r, c).value for c in range(1, len(OUTPUT_COLUMNS) + 2)):
            next_row = r + 1
            break

    log.info(f"Writing {len(rows)} rows starting at row {next_row}")

    for row_dict in rows:
        for col_name in output_columns:
            col_idx = header_map.get(col_name.strip())
            if col_idx is None:
                continue
            val = row_dict.get(col_name, "")
            ws.cell(row=next_row, column=col_idx, value=val)
        next_row += 1

    # Refresh dropdown
    _apply_dropdown(ws, header_map)

    _save_and_upload(wb)
    return len(rows)


def apply_progress_dropdown() -> None:
    """Re-apply Progress Report dropdown. Safe to call anytime."""
    wb, ws, _ = _open_master()
    header_map = {
        str(ws.cell(1, c).value).strip(): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(1, c).value
    }
    _apply_dropdown(ws, header_map)
    _save_and_upload(wb)


def _apply_dropdown(ws, header_map: dict):
    col_idx = header_map.get("Progress Report")
    if col_idx is None:
        return
    col_letter = openpyxl.utils.get_column_letter(col_idx)
    last_row   = max(ws.max_row, 1000)
    dv_range   = f"{col_letter}2:{col_letter}{last_row}"

    ws.data_validations.dataValidation = [
        v for v in ws.data_validations.dataValidation
        if col_letter not in str(v.sqref)
    ]
    dv = DataValidation(
        type="list",
        formula1=f'"{PROGRESS_OPTIONS}"',
        allow_blank=True,
        showDropDown=False,
        showErrorMessage=True,
        errorTitle="Invalid option",
        error="Please choose a value from the dropdown list.",
    )
    dv.sqref = dv_range
    ws.add_data_validation(dv)


# ─────────────────────────────────────────────
# Read sheet data (for Solicitations page)
# ─────────────────────────────────────────────

def read_master_sheet():
    """Download master sheet and return data as a pandas DataFrame."""
    import pandas as pd

    wb, ws = _open_master_readonly()
    try:
        all_rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not all_rows:
        return pd.DataFrame()

    headers = [str(v) if v is not None else f"Col{i+1}" for i, v in enumerate(all_rows[0])]
    data = [list(row) for row in all_rows[1:] if any(v is not None for v in row)]

    df = pd.DataFrame(data, columns=headers)
    if "Progress Report" in df.columns:
        df["Progress Report"] = df["Progress Report"].fillna("").astype(str).replace("None", "")
    return df


def delete_expired_rows(sheet_row_numbers: list) -> int:
    """Delete the given 1-indexed sheet row numbers from the master sheet and re-upload."""
    if not sheet_row_numbers:
        return 0
    wb, ws, _ = _open_master()
    for row_num in sorted(sheet_row_numbers, reverse=True):
        ws.delete_rows(row_num)
    _save_and_upload(wb)
    log.info(f"Deleted {len(sheet_row_numbers)} expired row(s) from master sheet")
    return len(sheet_row_numbers)


def update_progress_reports(row_updates: dict) -> int:
    """
    Write Progress Report values back to the master sheet.

    row_updates: {sheet_row_number (int, 1-indexed, data starts at row 2): new_status (str)}
    Returns count of rows updated.
    """
    if not row_updates:
        return 0

    wb, ws, _ = _open_master()

    # Locate Progress Report column
    headers = {str(ws.cell(1, c).value).strip(): c for c in range(1, ws.max_column + 1)}
    prog_col = headers.get("Progress Report")
    if not prog_col:
        raise ValueError("'Progress Report' column not found in master sheet")

    count = 0
    for sheet_row, new_status in row_updates.items():
        if 2 <= int(sheet_row) <= ws.max_row:
            ws.cell(row=int(sheet_row), column=prog_col, value=new_status or None)
            count += 1

    if count:
        _save_and_upload(wb)
        log.info(f"Updated {count} Progress Report value(s) in master sheet")

    return count


# ─────────────────────────────────────────────
# Date helper (single value, no pandas)
# ─────────────────────────────────────────────

def _parse_date(val):
    """Parse a cell value to a date object. Returns None if unparseable."""
    from datetime import date, datetime as dt
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, dt):
        return val
    if isinstance(val, dt):
        return val.date()
    s = str(val).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────
# Urgent tab
# ─────────────────────────────────────────────

def _ensure_urgent_tab(wb):
    """Return the Urgent worksheet, creating it with headers if needed."""
    if URGENT_TAB_NAME not in wb.sheetnames:
        ws = wb.create_sheet(URGENT_TAB_NAME)
        fill = PatternFill("solid", fgColor="C00000")
        font = Font(bold=True, color="FFFFFF")
        for col_idx, col_name in enumerate(OUTPUT_COLUMNS, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font      = font
            cell.fill      = fill
            cell.alignment = Alignment(horizontal="center")
        widths = [20, 40, 35, 18, 18, 20, 35, 40, 20, 18]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        log.info(f"Created '{URGENT_TAB_NAME}' sheet tab")
    return wb[URGENT_TAB_NAME]


def refresh_urgent_tab() -> tuple:
    """
    Sync the Urgent sheet tab from the main Opportunities sheet:
      - Remove rows where due_date < today (expired)
      - Add rows where today <= due_date < today+10 not already present
    Returns (removed, added).
    """
    from datetime import date, timedelta
    today        = date.today()
    urgent_limit = today + timedelta(days=10)

    wb, ws_main, _ = _open_master()
    ws_urg = _ensure_urgent_tab(wb)

    # Column index helpers for main sheet
    main_hdrs = {
        str(ws_main.cell(1, c).value or "").strip(): c
        for c in range(1, ws_main.max_column + 1)
    }
    def _mc(name): return main_hdrs.get(name)

    due_col  = _mc("Due Date")
    sol_col  = _mc("Solicitation Number")
    link_col = _mc("UiLink")

    # Collect urgent-window rows from main sheet
    candidate_rows = []   # list of (sol, link, [cell values])
    for r in range(2, ws_main.max_row + 1):
        due = _parse_date(ws_main.cell(r, due_col).value) if due_col else None
        if due and today <= due < urgent_limit:
            sol  = str(ws_main.cell(r, sol_col).value  or "").strip() if sol_col  else ""
            link = str(ws_main.cell(r, link_col).value or "").strip() if link_col else ""
            vals = [ws_main.cell(r, c).value for c in range(1, len(OUTPUT_COLUMNS) + 1)]
            candidate_rows.append((sol, link, vals))

    # Column helpers for Urgent tab
    urg_hdrs = {
        str(ws_urg.cell(1, c).value or "").strip(): c
        for c in range(1, ws_urg.max_column + 1)
    }
    def _uc(name): return urg_hdrs.get(name)

    urg_due_col  = _uc("Due Date")
    urg_sol_col  = _uc("Solicitation Number")
    urg_link_col = _uc("UiLink")

    # Scan Urgent tab: collect existing keys and mark expired rows for deletion
    existing_sols  = set()
    existing_links = set()
    to_delete = []

    for r in range(2, ws_urg.max_row + 1):
        due = _parse_date(ws_urg.cell(r, urg_due_col).value) if urg_due_col else None
        if not due:
            continue
        if due < today:
            to_delete.append(r)
            continue
        if urg_sol_col:
            v = str(ws_urg.cell(r, urg_sol_col).value or "").strip()
            if v: existing_sols.add(v)
        if urg_link_col:
            v = str(ws_urg.cell(r, urg_link_col).value or "").strip()
            if v: existing_links.add(v)

    # Delete expired rows (reverse order to keep row numbers stable)
    for r in sorted(to_delete, reverse=True):
        ws_urg.delete_rows(r)
    removed = len(to_delete)

    # Find next empty row
    last_r = 1
    for r in range(ws_urg.max_row, 1, -1):
        if any(ws_urg.cell(r, c).value for c in range(1, len(OUTPUT_COLUMNS) + 2)):
            last_r = r
            break

    # Append new urgent rows
    added = 0
    for sol, link, vals in candidate_rows:
        is_dupe = (sol and sol in existing_sols) or (link and link in existing_links)
        if not is_dupe:
            last_r += 1
            for c, v in enumerate(vals, 1):
                ws_urg.cell(last_r, c, v)
            if sol:  existing_sols.add(sol)
            if link: existing_links.add(link)
            added += 1

    _save_and_upload(wb)
    log.info(f"Urgent tab: {removed} expired removed, {added} new rows added")
    return removed, added


def read_urgent_tab():
    """Return the Urgent sheet tab as a DataFrame."""
    import pandas as pd
    raw = download_drive_file(SPREADSHEET_FILE_ID)
    wb  = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    if URGENT_TAB_NAME not in wb.sheetnames:
        wb.close()
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    ws = wb[URGENT_TAB_NAME]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    headers = [str(v) if v is not None else f"Col{i}" for i, v in enumerate(rows[0])]
    data    = [list(r) for r in rows[1:] if any(v is not None for v in r)]
    df = pd.DataFrame(data, columns=headers)
    if "Progress Report" in df.columns:
        df["Progress Report"] = df["Progress Report"].fillna("").astype(str).replace("None", "")
    return df


# ─────────────────────────────────────────────
# Overdue cleanup (main sheet)
# ─────────────────────────────────────────────

def cleanup_overdue_rows() -> int:
    """
    Delete rows from the main sheet where:
      - due_date is more than 5 days in the past
      - Progress Report is empty
    Returns number of rows deleted.
    """
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=5)

    wb, ws, _ = _open_master()
    hdrs = {str(ws.cell(1, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}
    due_col  = hdrs.get("Due Date")
    prog_col = hdrs.get("Progress Report")

    to_delete = []
    for r in range(2, ws.max_row + 1):
        due  = _parse_date(ws.cell(r, due_col).value) if due_col  else None
        prog = str(ws.cell(r, prog_col).value or "").strip() if prog_col else ""
        if due and due < cutoff and not prog:
            to_delete.append(r)

    for r in sorted(to_delete, reverse=True):
        ws.delete_rows(r)

    if to_delete:
        _save_and_upload(wb)
        log.info(f"Cleaned up {len(to_delete)} overdue empty-progress rows")

    return len(to_delete)