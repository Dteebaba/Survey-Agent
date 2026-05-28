"""
Google Drive and Sheets connector.
Since the target spreadsheet is an .xlsx Office file (not a native Google Sheet),
we use a download-append-reupload pattern via the Drive API.
Tokens are read from token_store.py (.connector_tokens.json).
"""
import io
import logging
import os
import requests
import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from token_store import clear_tokens, get_proxy_config

log = logging.getLogger(__name__)

# Google Drive API base (direct)
_DRIVE_BASE = "https://www.googleapis.com"


def _drive_request(method: str, path: str, *, params=None, data=None,
                   headers_extra=None, timeout=30) -> requests.Response:
    """
    Make a Drive API request via Replit's connectors proxy.
    Automatically refreshes proxy headers on 401 and retries once.
    `path` should start with '/drive/v3/...' or '/upload/drive/v3/...'.
    """
    for attempt in range(2):
        try:
            cfg = get_proxy_config()
        except Exception as e:
            raise RuntimeError(f"Cannot get proxy config: {e}") from e

        proxy_url = cfg["proxy_url"]
        headers = dict(cfg["proxy_headers"])
        if headers_extra:
            headers.update(headers_extra)

        url = proxy_url + path
        resp = requests.request(
            method, url,
            params=params, data=data,
            headers=headers, timeout=timeout,
        )
        if resp.status_code == 401 and attempt == 0:
            log.warning("⚠️  401 from proxy — clearing cache and refreshing…")
            clear_tokens()
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp

SPREADSHEET_FILE_ID = os.getenv("GOOGLE_SHEETS_ID", "151jig9_3v-__dHfk7TksitJYONDMOLQV")
SHEET_TAB_NAME = "Sheet3"


# -------------------------------------------------
# Google Drive helpers
# -------------------------------------------------

def list_drive_files(folder_id: str) -> list:
    resp = _drive_request(
        "GET",
        "/drive/v3/files",
        params={
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "files(id,name,mimeType,modifiedTime,createdTime)",
            "orderBy": "createdTime desc",
            "pageSize": 200,
        },
        timeout=30,
    )
    return resp.json().get("files", [])


def download_drive_file(file_id: str) -> bytes:
    resp = _drive_request(
        "GET",
        f"/drive/v3/files/{file_id}",
        params={"alt": "media"},
        timeout=60,
    )
    return resp.content


def upload_drive_file(file_id: str, content: bytes, mime_type: str) -> dict:
    """Update an existing file in Drive with new content."""
    resp = _drive_request(
        "PATCH",
        f"/upload/drive/v3/files/{file_id}",
        params={"uploadType": "media"},
        data=content,
        headers_extra={"Content-Type": mime_type},
        timeout=60,
    )
    return resp.json()


# -------------------------------------------------
# xlsx append helpers (Drive-based, works with Office files)
# -------------------------------------------------

def get_existing_dedup_keys() -> tuple[set, set]:
    """
    Download the master xlsx and return two dedup sets:
      (solicitation_numbers, uilinks)
    Both are used for deduplication — UiLink is the fallback when
    Solicitation Number is blank in the source data.
    """
    try:
        raw = download_drive_file(SPREADSHEET_FILE_ID)
        wb = openpyxl.load_workbook(io.BytesIO(raw))
        ws = wb[SHEET_TAB_NAME]

        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]

        def _find_col(name: str) -> int | None:
            for i, h in enumerate(headers):
                if h and str(h).strip().lower() == name.lower():
                    return i + 1
            return None

        sol_col = _find_col("Solicitation Number")
        link_col = _find_col("UiLink")

        sol_nums: set = set()
        uilinks: set = set()

        for row in range(2, ws.max_row + 1):
            if sol_col:
                v = ws.cell(row, sol_col).value
                if v:
                    sol_nums.add(str(v).strip())
            if link_col:
                v = ws.cell(row, link_col).value
                if v:
                    uilinks.add(str(v).strip())

        return sol_nums, uilinks
    except Exception:
        return set(), set()


def get_existing_solicitation_numbers() -> set:
    """Legacy wrapper — returns solicitation numbers only."""
    sol_nums, _ = get_existing_dedup_keys()
    return sol_nums


def append_rows_to_xlsx(rows: list, output_columns: list) -> int:
    """
    Download master xlsx, append rows, re-upload.
    rows: list of dicts keyed by output_columns names.
    Returns number of rows appended.
    """
    raw = download_drive_file(SPREADSHEET_FILE_ID)
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = wb[SHEET_TAB_NAME]

    # Map header names to column indices (strip whitespace for matching)
    header_map = {}
    for c in range(1, ws.max_column + 1):
        val = ws.cell(1, c).value
        if val:
            header_map[str(val).strip()] = c

    # Determine next empty row
    next_row = ws.max_row + 1

    for row_dict in rows:
        for col_name in output_columns:
            col_idx = header_map.get(col_name.strip())
            if col_idx is None:
                continue
            cell_val = row_dict.get(col_name, "")
            ws.cell(row=next_row, column=col_idx, value=cell_val)
        next_row += 1

    # Add / refresh dropdown validation on "Progress Report" column (col I = 9)
    PROGRESS_OPTIONS = (
        "Bid Submitted,Bid InProgress,Sub Contractor Inquiry,"
        "Bid Past Due Date,Bid Quote Requested"
    )
    progress_col_idx = header_map.get("Progress Report")
    if progress_col_idx is None:
        # Fallback: find by stripping trailing spaces
        for h, idx in header_map.items():
            if h.strip() == "Progress Report":
                progress_col_idx = idx
                break

    if progress_col_idx is not None:
        col_letter = openpyxl.utils.get_column_letter(progress_col_idx)
        last_data_row = ws.max_row
        dv_range = f"{col_letter}2:{col_letter}{max(last_data_row, 1000)}"

        # Remove any existing validation on this column to avoid duplicates
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

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    upload_drive_file(
        SPREADSHEET_FILE_ID,
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return len(rows)


def apply_progress_dropdown() -> None:
    """
    Download the master xlsx, add the Progress Report dropdown to column I
    (all data rows), and re-upload. Safe to call at any time.
    """
    PROGRESS_OPTIONS = (
        "Bid Submitted,Bid InProgress,Sub Contractor Inquiry,"
        "Bid Past Due Date,Bid Quote Requested"
    )

    raw = download_drive_file(SPREADSHEET_FILE_ID)
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = wb[SHEET_TAB_NAME]

    # Locate Progress Report column
    progress_col_idx = None
    for c in range(1, ws.max_column + 1):
        val = ws.cell(1, c).value
        if val and str(val).strip() == "Progress Report":
            progress_col_idx = c
            break

    if progress_col_idx is None:
        return

    col_letter = openpyxl.utils.get_column_letter(progress_col_idx)
    last_row = max(ws.max_row, 1000)
    dv_range = f"{col_letter}2:{col_letter}{last_row}"

    # Remove existing validations on this column
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

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    upload_drive_file(
        SPREADSHEET_FILE_ID,
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
