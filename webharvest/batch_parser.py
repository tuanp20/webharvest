"""
batch_parser — Parse URL lists from Excel, CSV, and Google Sheets.

Supported sources:
  - Excel (.xlsx) via openpyxl
  - CSV (.csv) via built-in csv module (auto-detect encoding & separator)
  - Google Sheets public link → auto-convert to CSV export

Returns a ParseResult with validated, deduplicated URLs + diagnostic info.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("webharvest.batch_parser")

# Max URLs per batch to prevent abuse / resource exhaustion
MAX_BATCH_SIZE = 50

# Google Sheets URL pattern
_GSHEET_RE = re.compile(
    r"https?://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", re.IGNORECASE
)


@dataclass
class ParseResult:
    """Result of parsing a batch URL source."""
    urls: List[str] = field(default_factory=list)
    total_rows: int = 0
    valid_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    errors: List[str] = field(default_factory=list)
    source_type: str = ""  # "excel", "csv", "google_sheets"


def _is_valid_url(text: str) -> bool:
    """Check if a string looks like a valid HTTP(S) URL."""
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    if not text.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(text)
        return bool(parsed.scheme and parsed.netloc and "." in parsed.netloc)
    except Exception:
        return False


def _extract_urls_from_rows(rows: List[List[str]], result: ParseResult) -> None:
    """Extract valid URLs from rows, scanning all columns.

    Strategy:
      1. Try column A first (most common)
      2. If column A has no URLs, scan all columns
      3. Auto-skip header rows (non-URL first row)
    """
    seen: set[str] = set()
    result.total_rows = len(rows)

    for row_idx, row in enumerate(rows):
        if not row:
            continue

        # Try each cell in the row to find a URL
        found_url = None
        for cell in row:
            if cell and isinstance(cell, str):
                cell = cell.strip()
                if _is_valid_url(cell):
                    found_url = cell
                    break

        if found_url:
            if found_url in seen:
                result.duplicate_count += 1
            else:
                seen.add(found_url)
                result.urls.append(found_url)
                result.valid_count += 1
        else:
            result.skipped_count += 1

    # Enforce batch size limit
    if len(result.urls) > MAX_BATCH_SIZE:
        result.errors.append(
            f"Danh sách có {len(result.urls)} URL, giới hạn tối đa {MAX_BATCH_SIZE}. "
            f"Chỉ lấy {MAX_BATCH_SIZE} URL đầu tiên."
        )
        result.urls = result.urls[:MAX_BATCH_SIZE]
        result.valid_count = len(result.urls)


def parse_excel(file_content: bytes, filename: str = "") -> ParseResult:
    """Parse URLs from an Excel (.xlsx) file.

    Parameters
    ----------
    file_content : bytes
        Raw bytes of the uploaded Excel file.
    filename : str
        Original filename (for logging).

    Returns
    -------
    ParseResult
        Parsed and validated URL list.
    """
    result = ParseResult(source_type="excel")

    try:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            result.errors.append("File Excel không có sheet nào.")
            return result

        rows: List[List[str]] = []
        for row in ws.iter_rows(values_only=True):
            str_row = [str(cell).strip() if cell is not None else "" for cell in row]
            rows.append(str_row)

        wb.close()
        _extract_urls_from_rows(rows, result)

    except ImportError:
        result.errors.append("Thư viện openpyxl chưa được cài đặt. Chạy: pip install openpyxl")
    except Exception as e:
        logger.error("Error parsing Excel file %s: %s", filename, e)
        result.errors.append(f"Lỗi đọc file Excel: {e}")

    return result


def parse_csv(file_content: bytes, filename: str = "") -> ParseResult:
    """Parse URLs from a CSV file with auto-detect encoding and separator.

    Parameters
    ----------
    file_content : bytes
        Raw bytes of the uploaded CSV file.
    filename : str
        Original filename (for logging).

    Returns
    -------
    ParseResult
        Parsed and validated URL list.
    """
    result = ParseResult(source_type="csv")

    # Auto-detect encoding: try UTF-8 BOM → UTF-8 → latin-1
    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = file_content.decode(encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue

    if text is None:
        result.errors.append("Không thể đọc file CSV — encoding không hỗ trợ.")
        return result

    try:
        # Auto-detect separator using csv.Sniffer
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel  # fallback to comma-separated

        reader = csv.reader(io.StringIO(text), dialect)
        rows = [row for row in reader]

        _extract_urls_from_rows(rows, result)

    except Exception as e:
        logger.error("Error parsing CSV file %s: %s", filename, e)
        result.errors.append(f"Lỗi đọc file CSV: {e}")

    return result


def parse_file(file_content: bytes, filename: str) -> ParseResult:
    """Parse URLs from an uploaded file (Excel or CSV).

    Dispatches to the appropriate parser based on file extension.

    Parameters
    ----------
    file_content : bytes
        Raw bytes of the uploaded file.
    filename : str
        Original filename with extension.

    Returns
    -------
    ParseResult
        Parsed and validated URL list.
    """
    ext = Path(filename).suffix.lower()

    if ext in (".xlsx", ".xls"):
        return parse_excel(file_content, filename)
    elif ext in (".csv", ".tsv", ".txt"):
        return parse_csv(file_content, filename)
    else:
        result = ParseResult()
        result.errors.append(
            f"Định dạng file '{ext}' không được hỗ trợ. "
            "Vui lòng sử dụng .xlsx, .csv, hoặc .txt"
        )
        return result


async def parse_google_sheet(sheet_url: str) -> ParseResult:
    """Parse URLs from a public Google Sheets link.

    Converts the Google Sheets URL to a CSV export URL and downloads it.

    Parameters
    ----------
    sheet_url : str
        Public Google Sheets URL (must be viewable by anyone with the link).

    Returns
    -------
    ParseResult
        Parsed and validated URL list.
    """
    result = ParseResult(source_type="google_sheets")

    # Extract spreadsheet ID
    match = _GSHEET_RE.search(sheet_url)
    if not match:
        result.errors.append(
            "Link Google Sheets không hợp lệ. "
            "Vui lòng sử dụng link dạng: https://docs.google.com/spreadsheets/d/XXXXX/..."
        )
        return result

    spreadsheet_id = match.group(1)

    # Detect gid (sheet tab ID) if present in URL
    gid = "0"  # default first sheet
    gid_match = re.search(r"[?&#]gid=(\d+)", sheet_url)
    if gid_match:
        gid = gid_match.group(1)

    # Build CSV export URL
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/export?format=csv&gid={gid}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(csv_url)

            if resp.status_code == 404:
                result.errors.append(
                    "Không tìm thấy Google Sheet. Kiểm tra link và quyền truy cập "
                    "(Sheet phải ở chế độ 'Bất kỳ ai có link đều xem được')."
                )
                return result

            if resp.status_code != 200:
                result.errors.append(
                    f"Không thể tải Google Sheet (HTTP {resp.status_code}). "
                    "Kiểm tra link và đảm bảo Sheet ở chế độ public."
                )
                return result

            # Check if response is HTML (likely an auth page)
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                result.errors.append(
                    "Google Sheet yêu cầu đăng nhập. "
                    "Vui lòng đặt quyền chia sẻ: 'Bất kỳ ai có link đều xem được'."
                )
                return result

            csv_result = parse_csv(resp.content, "google_sheet.csv")
            result.urls = csv_result.urls
            result.total_rows = csv_result.total_rows
            result.valid_count = csv_result.valid_count
            result.skipped_count = csv_result.skipped_count
            result.duplicate_count = csv_result.duplicate_count
            result.errors.extend(csv_result.errors)

    except httpx.TimeoutException:
        result.errors.append(
            "Timeout khi tải Google Sheet (15s). Kiểm tra kết nối mạng hoặc thử lại."
        )
    except httpx.ConnectError:
        result.errors.append(
            "Không thể kết nối đến Google Sheets. "
            "Kiểm tra kết nối mạng hoặc firewall."
        )
    except Exception as e:
        logger.error("Error parsing Google Sheet %s: %s", sheet_url, e)
        result.errors.append(f"Lỗi khi tải Google Sheet: {e}")

    return result
