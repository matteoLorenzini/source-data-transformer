"""Google Drive and Google Sheets access: id parsing, authentication, and downloads."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

import requests

from .source_xml import sanitize_filename


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
