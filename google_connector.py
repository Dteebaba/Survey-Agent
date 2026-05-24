"""
Google Drive and Sheets connector.
Since the target spreadsheet is an .xlsx Office file (not a native Google Sheet),
we use a download-append-reupload pattern via the Drive API.
Tokens are read from token_store.py (.connector_tokens.json).
"""
import io
import os
import requests
import openpyxl
from token_store import get_token

SPREADSHEET_FILE_ID = os.getenv("GOOGLE_SHEETS_ID", "151jig9_3v-__dHfk7TksitJYONDMOLQV")
SHEET_TAB_NAME = "Sheet2"


# -------------------------------------------------
# Google Drive helpers
# -------------------------------------------------

def list_drive_files(folder_id: str) -> list:
    token = get_token("google-drive")
    url = "https://www.googleapis.com/drive/v3/files"
    params = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,modifiedTime,createdTime)",
        "orderBy": "createdTime desc",
        "pageSize": 200,
    }
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("files", [])


def download_drive_file(file_id: str) -> bytes:
    token = get_token("google-drive")
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    params = {"alt": "media"}
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content


def upload_drive_file(file_id: str, content: bytes, mime_type: str) -> dict:
    """Update an existing file in Drive with new content."""
    token = get_token("google-drive")
    url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}"
    params = {"uploadType": "media"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": mime_type,
    }
    resp = requests.patch(url, params=params, headers=headers, data=content, timeout=60)
    resp.raise_for_status()
    return resp.json()


# -------------------------------------------------
# xlsx append helpers (Drive-based, works with Office files)
# -------------------------------------------------

def get_existing_solicitation_numbers() -> set:
    """Download the master xlsx and return existing solicitation numbers."""
    try:
        raw = download_drive_file(SPREADSHEET_FILE_ID)
        wb = openpyxl.load_workbook(io.BytesIO(raw))
        ws = wb[SHEET_TAB_NAME]

        # Find "Solicitation Number" column index
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        sol_col = None
        for i, h in enumerate(headers):
            if h and str(h).strip().lower() == "solicitation number":
                sol_col = i + 1
                break

        if sol_col is None:
            return set()

        nums = set()
        for row in range(2, ws.max_row + 1):
            val = ws.cell(row, sol_col).value
            if val:
                nums.add(str(val).strip())
        return nums
    except Exception:
        return set()


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

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    upload_drive_file(
        SPREADSHEET_FILE_ID,
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return len(rows)
