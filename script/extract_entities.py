"""Extract entities from free-text spreadsheet columns into a reviewable JSON file.

Usage:
    extract_entities.py --file <XLSX> --fields Biography Role Contribution
    extract_entities.py --file <XLSX> --fields Biography --subject-field Name_Surname --dry-run

Uses a local Ollama server by default (http://localhost:11434/v1, model qwen2.5:7b);
no API key or account is needed. LLM_BASE_URL, LLM_MODEL and LLM_API_KEY select another
OpenAI-compatible endpoint. Results are cached per cell text, so re-runs only call
the model for new or changed cells. Pass the JSON to download_drive_excel.py with --entities.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook

from transformer.cli import DEFAULT_OUTPUT_DIR
from transformer.entities import (
    clean_text,
    item_key,
    load_store,
    new_store,
    save_store,
    validate_entities,
)
from transformer.llm_extractor import config_from_env, extract_entities
from transformer.source_xml import canonical_header_key, worksheet_to_source_xml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract entities from free-text columns of a workbook.")
    parser.add_argument("--file", type=Path, required=True, help="Local .xlsx workbook.")
    parser.add_argument("--sheet-name", help="Process only this worksheet; by default all worksheets.")
    parser.add_argument("--fields", nargs="+", required=True, help="Header names of the free-text columns.")
    parser.add_argument("--subject-field", default="Name_Surname", help="Header of the column naming the record subject.")
    parser.add_argument("--output", type=Path, help="Entity JSON path; defaults to output_data/<workbook>_entities.json.")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL; defaults to LLM_BASE_URL or local Ollama.")
    parser.add_argument("--model", help="Model name; defaults to LLM_MODEL or qwen2.5:7b.")
    parser.add_argument("--refresh", action="store_true", help="Re-extract cells that are already cached.")
    parser.add_argument("--dry-run", action="store_true", help="List the cells that would be sent, without calling the model.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    workbook_path = args.file.resolve()
    if not workbook_path.is_file():
        parser.error(f"Workbook does not exist: {workbook_path}")

    output_path = args.output or DEFAULT_OUTPUT_DIR / f"{workbook_path.stem}_entities.json"
    field_keys = [canonical_header_key(name) for name in args.fields]
    subject_key = canonical_header_key(args.subject_field)

    workbook = load_workbook(workbook_path, data_only=True)
    if args.sheet_name:
        if args.sheet_name not in workbook.sheetnames:
            parser.error(f"Worksheet {args.sheet_name!r} not found. Available: {', '.join(workbook.sheetnames)}")
        worksheets = [workbook[args.sheet_name]]
    else:
        worksheets = workbook.worksheets

    config = None if args.dry_run else config_from_env(args.base_url, args.model)
    store = new_store(config.model if config else "")
    if output_path.is_file():
        try:
            store = load_store(output_path)
        except ValueError as exc:
            parser.error(str(exc))
    if config:
        store["model"] = config.model

    extracted = skipped = dropped_total = 0
    for worksheet in worksheets:
        for row in worksheet_to_source_xml(worksheet).iter("row"):
            cells = {cell.get("key"): cell.text or "" for cell in row.findall("cell")}
            subject = cells.get(subject_key, "").strip()
            for field_key in field_keys:
                text = clean_text(cells.get(field_key, ""))
                if not text:
                    continue
                key = item_key(field_key, text)
                if key in store["items"] and not args.refresh:
                    skipped += 1
                    continue

                label = f"{worksheet.title} row {row.get('index')} {field_key}"
                if args.dry_run:
                    print(f"Would extract: {label} ({len(text)} chars)")
                    continue

                print(f"Extracting: {label}...")
                raw = extract_entities(config, field_key, subject, text)
                entities, dropped = validate_entities(raw, text)
                dropped_total += dropped
                store["items"][key] = {
                    "field": field_key,
                    "preview": text[:80],
                    "entities": entities,
                }
                save_store(output_path, store)
                extracted += 1

    print(f"Extracted {extracted} cells, reused {skipped} cached, dropped {dropped_total} invalid entities.")
    if extracted:
        print(f"Entities written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
