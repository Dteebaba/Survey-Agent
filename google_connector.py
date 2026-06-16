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
SHEET_TAB_NAME      = "Opportunities"   # ← new clean tab name

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
    """Download master xlsx. Returns (wb, ws, raw_bytes)."""
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

    _, ws, _ = _open_master()

    if ws.max_row < 1:
        return pd.DataFrame()

    headers = [ws.cell(1, c).value or f"Col{c}" for c in range(1, ws.max_column + 1)]

    rows = []
    for r in range(2, ws.max_row + 1):
        vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if any(v is not None for v in vals):
            rows.append(vals)

    df = pd.DataFrame(rows, columns=headers)
    # Ensure Progress Report exists as a string column
    if "Progress Report" in df.columns:
        df["Progress Report"] = df["Progress Report"].fillna("").astype(str).replace("None", "")
    return df


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