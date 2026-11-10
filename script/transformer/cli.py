"""Command-line interface for download_drive_excel.py."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Callable, Iterable
from xml.etree.ElementTree import Element

from openpyxl import load_workbook

from .entities import attach_entities, load_store
from .entity_tables import write_entity_tables
from .google_drive import (
    download_google_sheet_as_csv,
    download_google_sheet_as_xlsx,
    extract_file_id,
    extract_sheet_gid,
    print_credentials_help,
    resolve_access_token,
)
from .source_xml import rows_to_source_xml, sanitize_filename, worksheet_to_source_xml
from .xslt_runner import load_stylesheet, load_stylesheet_mapping, write_source_exports

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output_data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download a Google Sheet and export each worksheet to CSV and XML.")
    parser.add_argument(
        "--credentials-help",
        action="store_true",
        help="Print authentication setup instructions for private Google Sheets and exit.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Local .xlsx workbook to process without downloading from Google.",
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
        "--sheet-name",
        help="Export only this worksheet from a workbook; by default all worksheets are exported.",
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
    parser.add_argument(
        "--stylesheet-map",
        type=Path,
        help="XSLT file to use directly, or JSON mapping of Google Drive file IDs to XSLT paths.",
    )
    parser.add_argument(
        "--sample-row",
        type=int,
        help="Sheet row number for the single-record <name>_sample.xml export; defaults to the first data row.",
    )
    parser.add_argument(
        "--entities",
        type=Path,
        help="Entity JSON produced by extract_entities.py; writes <name>_entities.xml with the entities of each row.",
    )
    parser.add_argument(
        "--rdf-mapping",
        type=Path,
        action="append",
        help="YAML mapping (see mappings/) that turns an XML export into CIDOC-CRM RDF; repeat for several mappings. "
        "Its 'source' key selects <name>.xml, <name>_relations.xml, or <name>_entities.xml.",
    )
    parser.add_argument(
        "--rdf-format",
        default="turtle",
        help="RDF serialization for --rdf-mapping outputs: turtle, xml, nt, nquads, or trig.",
    )
    return parser


def resolve_stylesheet_path(parser: argparse.ArgumentParser, stylesheet_map: Path | None, stylesheet_key: str) -> Path:
    """Pick the stylesheet: the default, an explicit .xsl, or a JSON mapping entry."""

    if stylesheet_map is None:
        return SCRIPT_DIR / "xslt" / "default.xsl"
    if stylesheet_map.suffix.lower() in {".xsl", ".xslt"}:
        return stylesheet_map.resolve()

    try:
        stylesheet_mapping = load_stylesheet_mapping(stylesheet_map)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    stylesheet_path = stylesheet_mapping.get(stylesheet_key)
    if stylesheet_path is None:
        parser.error(f"No XSLT stylesheet configured for source {stylesheet_key}.")
    return stylesheet_path


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.credentials_help:
        print_credentials_help()
        return 0

    source_count = sum(bool(value) for value in (args.file, args.url, args.file_id))
    if source_count != 1:
        parser.error("provide exactly one of --file, --url, or --file-id")

    local_file_path = args.file.resolve() if args.file else None
    if local_file_path is not None:
        if not local_file_path.is_file():
            parser.error(f"Local workbook does not exist: {local_file_path}")
        if local_file_path.suffix.lower() != ".xlsx":
            parser.error("--file currently supports .xlsx workbooks")
        if args.gid:
            parser.error("--gid can only be used with --url or --file-id")
        stylesheet_key = local_file_path.stem
        file_id = None
        gid = None
        access_token = None
    else:
        raw_id = args.file_id or args.url
        assert raw_id is not None
        file_id = extract_file_id(raw_id)
        stylesheet_key = file_id
        gid = args.gid or extract_sheet_gid(raw_id)
        access_token = resolve_access_token(args.access_token, args.service_account_json)

    if gid is not None and args.sheet_name:
        parser.error("--sheet-name cannot be used with --gid, which already selects a single worksheet")

    stylesheet_path = resolve_stylesheet_path(parser, args.stylesheet_map, stylesheet_key)
    if not stylesheet_path.is_file():
        parser.error(f"XSLT stylesheet does not exist: {stylesheet_path}")
    try:
        stylesheet = load_stylesheet(stylesheet_path)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    entity_store = None
    if args.entities:
        try:
            entity_store = load_store(args.entities)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))

    rdf_mappings = []
    if args.rdf_mapping:
        from .rdf_mapper import export_rdf, load_mapping, serialization_format

        try:
            serialization_format(args.rdf_format)
            rdf_mappings = [load_mapping(mapping_path) for mapping_path in args.rdf_mapping]
        except (OSError, ValueError) as exc:
            parser.error(str(exc))

    def export(source_root: Element, csv_path: Path, xml_path: Path) -> None:
        write_source_exports(source_root, csv_path, xml_path, stylesheet, args.sample_row)
        if entity_store is not None:
            attach_entities(source_root, entity_store)
            entities_path = xml_path.with_name(f"{xml_path.stem}_entities{xml_path.suffix}")
            if write_entity_tables(source_root, entities_path):
                print(f"Writing entities to {entities_path}...")
        for rdf_mapping in rdf_mappings:
            export_rdf(rdf_mapping, xml_path, args.rdf_format)

    output_dir = Path(args.output_dir)
    workbook_dir = output_dir / args.base_name
    excel_path = workbook_dir / f"{args.base_name}.xlsx"

    if local_file_path is not None:
        print(f"Reading local workbook from {local_file_path}...")
        workbook = load_workbook(local_file_path, data_only=True)
    elif gid is not None:
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
            rows = [row for row in csv.reader(csv_file)]

        print(f"Writing XML to {xml_path}...")
        source_root = rows_to_source_xml(rows)
        try:
            export(source_root, csv_path, xml_path)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        print(f"Downloading Google Sheet {file_id} as Excel...")
        download_google_sheet_as_xlsx(file_id, excel_path, access_token=access_token)

        print(f"Reading workbook from {excel_path}...")
        workbook = load_workbook(excel_path, data_only=True)

    if gid is None:
        if args.sheet_name:
            if args.sheet_name not in workbook.sheetnames:
                parser.error(
                    f"Worksheet {args.sheet_name!r} not found. Available worksheets: "
                    f"{', '.join(workbook.sheetnames)}"
                )
            worksheets = [workbook[args.sheet_name]]
        else:
            worksheets = workbook.worksheets

        for worksheet in worksheets:
            sheet_slug = sanitize_filename(worksheet.title)
            csv_path = workbook_dir / f"{sheet_slug}.csv"
            xml_path = workbook_dir / f"{sheet_slug}.xml"

            print(f"Writing CSV to {csv_path}...")
            print(f"Writing XML to {xml_path}...")
            source_root = worksheet_to_source_xml(worksheet)
            try:
                export(source_root, csv_path, xml_path)
            except ValueError as exc:
                parser.error(str(exc))

    print("Done.")
    return 0
