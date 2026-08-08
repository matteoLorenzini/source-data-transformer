"""Download a Google Sheet as Excel and export every worksheet to CSV and XML.

Usage:
    download_drive_excel.py --file-id <GOOGLE_DRIVE_FILE_ID>
    download_drive_excel.py --url <GOOGLE_SHEETS_SHARE_URL>

The script downloads the spreadsheet as .xlsx, then writes one CSV and one XML
file per worksheet while preserving the grid layout of each sheet.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent

import requests
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

MULTI_VALUE_DELIMITER = "; "
MULTI_LABEL_COLUMNS = {"DISCRIMINANTE_TECNICA", "TECHNICAL_DIAGNOSTIC_FEATURES"}
MULTI_LABEL_ITEM_TAG = "value"
RELATION_COLUMNS = {"ATTACHES_TO", "SIMILAR_TO"}
RESOURCE_URI_PREFIX = "http://www.lynx.com/resource/cultural-heritage-object/"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output_data"


def print_credentials_help() -> None:
    """Print the supported authentication options for private sheets."""

    print("Credential options for private Google Sheets:")
    print("1. Service account JSON")
    print("   - Create a service account in Google Cloud.")
    print("   - Download the JSON key file.")
    print("   - Share the target Google Sheet with the service account email.")
    print("   - Run: python download_drive_excel.py --url <SHEET_URL> --service-account-json <PATH_TO_JSON>")
    print("2. OAuth2 access token")
    print("   - Generate a bearer token with access to the target Google Sheet.")
    print("   - Run: python download_drive_excel.py --url <SHEET_URL> --access-token <TOKEN>")
    print("   - Or set GOOGLE_ACCESS_TOKEN in the environment.")
    print("3. Public sheet")
    print("   - Make the Google Sheet readable by anyone with the link.")
    print("   - Run the script without authentication arguments.")


def extract_file_id(value: str) -> str:
    """Extract a Google Drive file id from a raw id or share URL."""

    patterns = [
        r"/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"/file/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return value.strip()


def extract_sheet_gid(value: str) -> str | None:
    """Extract a Google Sheets gid from a URL when one is present."""

    match = re.search(r"[?#&]gid=(\d+)", value)
    if match:
        return match.group(1)
    return None


def sanitize_filename(value: str) -> str:
    """Turn a worksheet title into a safe file name."""

    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return safe_value.strip("._") or "sheet"


def extract_sheet_name_from_content_disposition(
    content_disposition: str | None,
    fallback: str,
) -> str:
    """Extract sheet title from Content-Disposition header when available."""

    if not content_disposition:
        return fallback

    filename_star_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
    if filename_star_match:
        value = unquote(filename_star_match.group(1)).strip().strip('"')
    else:
        filename_match = re.search(r"filename=\"?([^\";]+)\"?", content_disposition, re.IGNORECASE)
        if not filename_match:
            return fallback
        value = filename_match.group(1).strip().strip('"')

    if value.lower().endswith(".csv"):
        value = value[:-4]

    return value.strip() or fallback


def normalize_cell_value(value) -> str:
    """Convert worksheet cell values into a single-line string."""

    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return MULTI_VALUE_DELIMITER.join(parts)

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in text:
        parts = [part.strip() for part in text.split("\n") if part.strip()]
        return MULTI_VALUE_DELIMITER.join(parts)

    return text


def sanitize_xml_tag(value: str, fallback: str) -> str:
    """Convert a header value into a safe XML element name."""

    normalized = normalize_cell_value(value).strip()
    tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", normalized)
    tag = re.sub(r"_+", "_", tag).strip("_.-")

    if not tag:
        tag = fallback

    if not re.match(r"^[A-Za-z_]", tag) or tag.lower().startswith("xml"):
        tag = f"col_{tag}"

    return tag


def canonical_header_key(value: str) -> str:
    """Normalize a header name for matching behavior rules."""

    return sanitize_xml_tag(value, "col").upper()


def split_multi_label_values(value) -> list[str]:
    """Split multi-select cell values into individual labels."""

    normalized = normalize_cell_value(value)
    if not normalized:
        return []

    parts = [part.strip() for part in re.split(r"[,;\n]+", normalized) if part.strip()]
    return parts


def split_relation_values(value) -> list[str]:
    """Split relation references (Project_ID values) from a cell."""

    normalized = normalize_cell_value(value)
    if not normalized:
        return []

    return [part.strip() for part in re.split(r"[,;\n]+", normalized) if part.strip()]


def find_column_index(header_row: list[str], target_header_key: str) -> int | None:
    """Find a column index by canonical header key."""

    for column_index, header_value in enumerate(header_row):
        if canonical_header_key(header_value) == target_header_key:
            return column_index
    return None


def build_project_unique_id_map(
    data_rows: list[list[str]],
    project_id_index: int,
    unique_id_index: int,
) -> dict[str, str]:
    """Map Project_ID values to their corresponding Unique_ID values."""

    mapping: dict[str, str] = {}
    for row in data_rows:
        if project_id_index >= len(row) or unique_id_index >= len(row):
            continue

        project_id = normalize_cell_value(row[project_id_index]).strip()
        unique_id = normalize_cell_value(row[unique_id_index]).strip()
        if project_id and unique_id and project_id not in mapping:
            mapping[project_id] = unique_id

    return mapping


def relation_unique_ids_text(value, project_unique_id_map: dict[str, str]) -> str:
    """Resolve relation references into corresponding Unique_ID values."""

    relation_values = split_relation_values(value)
    if not relation_values:
        return ""

    unique_ids: list[str] = []
    for relation_value in relation_values:
        mapped_unique_id = project_unique_id_map.get(relation_value)
        if mapped_unique_id:
            unique_ids.append(f"{RESOURCE_URI_PREFIX}{mapped_unique_id}")

    return MULTI_VALUE_DELIMITER.join(unique_ids)


def add_relation_unique_id_cells(
    parent_element: Element,
    tag_name: str,
    header_key: str,
    value,
    project_unique_id_map: dict[str, str],
    generated_relation_unique_id_headers: set[str],
) -> None:
    """Add relation unique ID elements for relation columns."""

    if header_key not in RELATION_COLUMNS:
        return

    relation_unique_id_header = f"{header_key}_UNIQUE_ID"
    if relation_unique_id_header not in generated_relation_unique_id_headers:
        return

    unique_id_element = SubElement(parent_element, f"{tag_name}_unique_id")
    unique_id_element.text = relation_unique_ids_text(value, project_unique_id_map)


def append_xml_cell(parent: Element, tag_name: str, value, is_multi_label: bool) -> None:
    """Append one XML cell, optionally expanding multi-label values into children."""

    if not is_multi_label:
        cell = SubElement(parent, tag_name)
        cell.text = normalize_cell_value(value)
        return

    container = SubElement(parent, tag_name)
    labels = split_multi_label_values(value)
    for label in labels:
        item = SubElement(container, MULTI_LABEL_ITEM_TAG)
        item.text = label


def build_column_tags(header_row: list[str], max_columns: int) -> list[str]:
    """Build unique XML element names from the worksheet header row."""

    tags: list[str] = []
    seen: dict[str, int] = {}

    for column_index in range(1, max_columns + 1):
        header_value = header_row[column_index - 1] if column_index - 1 < len(header_row) else ""
        fallback = f"col_{get_column_letter(column_index)}"
        base_tag = sanitize_xml_tag(header_value, fallback)

        seen_count = seen.get(base_tag, 0)
        seen[base_tag] = seen_count + 1
        tag_name = base_tag if seen_count == 0 else f"{base_tag}_{seen_count + 1}"
        tags.append(tag_name)

    return tags


def build_column_specs(header_row: list[str], max_columns: int) -> list[tuple[str, bool]]:
    """Build XML tag and behavior metadata for each column."""

    tags = build_column_tags(header_row, max_columns)
    specs: list[tuple[str, bool]] = []

    for column_index, tag_name in enumerate(tags, start=1):
        header_value = header_row[column_index - 1] if column_index - 1 < len(header_row) else ""
        header_key = canonical_header_key(header_value)
        specs.append((tag_name, header_key in MULTI_LABEL_COLUMNS))

    return specs


def build_relation_unique_id_headers(header_row: list[str]) -> set[str]:
    """Determine which relation unique ID headers should be generated."""

    header_keys = {canonical_header_key(header_value) for header_value in header_row}
    generated: set[str] = set()

    for relation_header in RELATION_COLUMNS:
        relation_unique_id_header = f"{relation_header}_UNIQUE_ID"
        if relation_header in header_keys and relation_unique_id_header not in header_keys:
            generated.add(relation_unique_id_header)

    return generated


def build_http_session() -> requests.Session:
    """Create an HTTP session with browser-like headers for Google exports."""

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def resolve_access_token(
    cli_access_token: str | None,
    service_account_json: str | None,
) -> str | None:
    """Resolve an OAuth2 bearer token from CLI, env var, or service account."""

    if cli_access_token:
        return cli_access_token

    env_token = os.getenv("GOOGLE_ACCESS_TOKEN")
    if env_token:
        return env_token

    if not service_account_json:
        return None

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Service account auth requires google-auth. Install it with: pip install google-auth"
        ) from exc

    credentials = service_account.Credentials.from_service_account_file(
        service_account_json,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    credentials.refresh(Request())
    return credentials.token


def raise_export_error(response: requests.Response, file_id: str, gid: str | None = None) -> None:
    """Raise a helpful error for Google export permission failures."""

    if response.status_code in (401, 403):
        target = f"file {file_id}" if gid is None else f"file {file_id} gid {gid}"
        raise RuntimeError(
            "Google denied access to "
            f"{target}. Make the sheet publicly readable or provide "
            "--access-token (or GOOGLE_ACCESS_TOKEN) for an authenticated export."
        )
    response.raise_for_status()


def download_google_sheet_as_xlsx(file_id: str, destination: Path, access_token: str | None = None) -> None:
    """Download a Google Sheets document as an .xlsx export."""

    url = f"https://docs.google.com/spreadsheets/d/{file_id}/export"
    session = build_http_session()
    if access_token:
        session.headers["Authorization"] = f"Bearer {access_token}"
    response = session.get(url, params={"format": "xlsx"}, stream=True, timeout=60)

    raise_export_error(response, file_id)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output_file:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output_file.write(chunk)


def download_google_sheet_as_csv(
    file_id: str,
    gid: str,
    output_dir: Path,
    access_token: str | None = None,
) -> tuple[Path, str]:
    """Download a single Google Sheets worksheet as CSV and return its path and sheet name."""

    url = f"https://docs.google.com/spreadsheets/d/{file_id}/export"
    session = build_http_session()
    if access_token:
        session.headers["Authorization"] = f"Bearer {access_token}"
    response = session.get(url, params={"format": "csv", "gid": gid}, stream=True, timeout=60)

    raise_export_error(response, file_id, gid)

    sheet_name = extract_sheet_name_from_content_disposition(
        response.headers.get("Content-Disposition"),
        fallback=f"gid_{gid}",
    )
    sheet_slug = sanitize_filename(sheet_name)
    destination = output_dir / f"{sheet_slug}.csv"

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output_file:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output_file.write(chunk)

    return destination, sheet_name


def worksheet_to_xml(worksheet) -> Element:
    """Convert a worksheet into XML using the header row as element names."""

    sheet_element = Element("scheda")
    max_columns = worksheet.max_column
    if worksheet.max_row < 1 or max_columns < 1:
        return sheet_element

    header_row = [
        normalize_cell_value(value)
        for value in next(
            worksheet.iter_rows(min_row=1, max_row=1, max_col=max_columns, values_only=True),
            (),
        )
    ]
    column_specs = build_column_specs(header_row, max_columns)
    project_id_index = find_column_index(header_row, "PROJECT_ID")
    unique_id_index = find_column_index(header_row, "UNIQUE_ID")

    data_rows = [
        [normalize_cell_value(value) for value in row]
        for row in worksheet.iter_rows(
            min_row=2,
            max_row=worksheet.max_row,
            max_col=max_columns,
            values_only=True,
        )
    ]

    project_unique_id_map: dict[str, str] = {}
    if project_id_index is not None and unique_id_index is not None:
        project_unique_id_map = build_project_unique_id_map(data_rows, project_id_index, unique_id_index)

    generated_relation_unique_id_headers = build_relation_unique_id_headers(header_row)

    for row_index, row in enumerate(data_rows, start=2):
        row_element = SubElement(sheet_element, "row", index=str(row_index))
        relation_element: Element | None = None
        for column_index, ((tag_name, is_multi_label), value) in enumerate(zip(column_specs, row), start=1):
            header_value = header_row[column_index - 1] if column_index - 1 < len(header_row) else ""
            header_key = canonical_header_key(header_value)

            if header_key in RELATION_COLUMNS:
                if relation_element is None:
                    relation_element = SubElement(row_element, "relation")
                append_xml_cell(relation_element, tag_name, value, False)
                add_relation_unique_id_cells(
                    relation_element,
                    tag_name,
                    header_key,
                    value,
                    project_unique_id_map,
                    generated_relation_unique_id_headers,
                )
                continue

            append_xml_cell(row_element, tag_name, value, is_multi_label)

    return sheet_element


def rows_to_xml(rows: list[list[str]]) -> Element:
    """Convert CSV-style rows into XML using header names as element names."""

    sheet_element = Element("scheda")
    if not rows:
        return sheet_element

    header_row = [normalize_cell_value(value) for value in rows[0]]
    max_columns = max(len(header_row), max((len(row) for row in rows), default=0))
    column_specs = build_column_specs(header_row, max_columns)
    project_id_index = find_column_index(header_row, "PROJECT_ID")
    unique_id_index = find_column_index(header_row, "UNIQUE_ID")
    normalized_data_rows: list[list[str]] = []

    for row in rows[1:]:
        normalized_row = [normalize_cell_value(value) for value in row]
        if len(normalized_row) < max_columns:
            normalized_row.extend([""] * (max_columns - len(normalized_row)))
        normalized_data_rows.append(normalized_row)

    project_unique_id_map: dict[str, str] = {}
    if project_id_index is not None and unique_id_index is not None:
        project_unique_id_map = build_project_unique_id_map(normalized_data_rows, project_id_index, unique_id_index)

    generated_relation_unique_id_headers = build_relation_unique_id_headers(header_row)

    for row_index, normalized_row in enumerate(normalized_data_rows, start=2):
        row_element = SubElement(sheet_element, "row", index=str(row_index))
        relation_element: Element | None = None
        for column_index, ((tag_name, is_multi_label), value) in enumerate(zip(column_specs, normalized_row), start=1):
            header_value = header_row[column_index - 1] if column_index - 1 < len(header_row) else ""
            header_key = canonical_header_key(header_value)

            if header_key in RELATION_COLUMNS:
                if relation_element is None:
                    relation_element = SubElement(row_element, "relation")
                append_xml_cell(relation_element, tag_name, value, False)
                add_relation_unique_id_cells(
                    relation_element,
                    tag_name,
                    header_key,
                    value,
                    project_unique_id_map,
                    generated_relation_unique_id_headers,
                )
                continue

            append_xml_cell(row_element, tag_name, value, is_multi_label)

    return sheet_element


def write_csv_and_xml(worksheet, csv_path: Path, xml_path: Path) -> None:
    """Write one worksheet to CSV and XML using the same cell grid."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        for row in worksheet.iter_rows(
            min_row=1,
            max_row=worksheet.max_row,
            max_col=worksheet.max_column,
            values_only=True,
        ):
            writer.writerow([normalize_cell_value(value) for value in row])

    root = worksheet_to_xml(worksheet)
    indent(root, space="    ")
    tree = ElementTree(root)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def write_rows_csv_and_xml(rows: list[list[str]], csv_path: Path, xml_path: Path, sheet_name: str) -> None:
    """Write CSV-style rows to matching CSV and XML files."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        for row in rows:
            writer.writerow([normalize_cell_value(value) for value in row])

    root = rows_to_xml(rows)
    indent(root, space="    ")
    tree = ElementTree(root)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download a Google Sheet and export each worksheet to CSV and XML.")
    parser.add_argument(
        "--credentials-help",
        action="store_true",
        help="Print authentication setup instructions for private Google Sheets and exit.",
    )
    parser.add_argument(
        "--url",
        help="Google Drive share URL containing the spreadsheet file id.",
    )
    parser.add_argument(
        "--file-id",
        help="Google Drive file id. Use this if you already know the id.",
    )
    parser.add_argument(
        "--gid",
        help="Google Sheets gid. If omitted, the script uses gid from the URL when present.",
    )
    parser.add_argument(
        "--access-token",
        help="OAuth2 bearer token for private Google Sheets export. Can also be set via GOOGLE_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "--service-account-json",
        help="Path to a Google service account key JSON used to generate an access token.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where the downloaded file and exports will be written.",
    )
    parser.add_argument(
        "--base-name",
        default="google_sheet_export",
        help="Base folder name used for the downloaded Excel file and worksheet exports.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.credentials_help:
        print_credentials_help()
        return 0

    if not args.url and not args.file_id:
        parser.error("provide either --url or --file-id")

    raw_id = args.file_id or args.url
    assert raw_id is not None
    file_id = extract_file_id(raw_id)
    gid = args.gid or extract_sheet_gid(raw_id)
    access_token = resolve_access_token(args.access_token, args.service_account_json)

    output_dir = Path(args.output_dir)
    workbook_dir = output_dir / args.base_name
    excel_path = workbook_dir / f"{args.base_name}.xlsx"

    if gid is not None:
        print(f"Downloading Google Sheet {file_id} gid {gid} as CSV...")
        csv_path, sheet_name = download_google_sheet_as_csv(
            file_id,
            gid,
            workbook_dir,
            access_token=access_token,
        )

        sheet_slug = sanitize_filename(sheet_name)
        xml_path = workbook_dir / f"{sheet_slug}.xml"

        print(f"Reading CSV from {csv_path}...")
        with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file)
            rows = [row for row in reader]

        print(f"Writing XML to {xml_path}...")
        write_rows_csv_and_xml(rows, csv_path, xml_path, sheet_name)
    else:
        print(f"Downloading Google Sheet {file_id} as Excel...")
        download_google_sheet_as_xlsx(file_id, excel_path, access_token=access_token)

        print(f"Reading workbook from {excel_path}...")
        workbook = load_workbook(excel_path, data_only=True)

        for worksheet in workbook.worksheets:
            sheet_slug = sanitize_filename(worksheet.title)
            csv_path = workbook_dir / f"{sheet_slug}.csv"
            xml_path = workbook_dir / f"{sheet_slug}.xml"

            print(f"Writing CSV to {csv_path}...")
            print(f"Writing XML to {xml_path}...")
            write_csv_and_xml(worksheet, csv_path, xml_path)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())