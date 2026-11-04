"""Serialize worksheet data into the neutral <source> XML consumed by the stylesheets."""

from __future__ import annotations

import copy
import re
from xml.etree.ElementTree import Element, SubElement

from openpyxl.utils import get_column_letter


def sanitize_filename(value: str) -> str:
    """Turn a worksheet title into a safe file name."""

    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return safe_value.strip("._") or "sheet"


def source_cell_text(value) -> str:
    """Convert a spreadsheet value to source text without applying field rules."""

    return "" if value is None else str(value)


def sanitize_xml_tag(value: str, fallback: str) -> str:
    """Convert a header value into a safe XML element name."""

    normalized = source_cell_text(value).strip()
    tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", normalized)
    tag = re.sub(r"_+", "_", tag).strip("_.-")

    if not tag:
        tag = fallback

    if not re.match(r"^[A-Za-z_]", tag) or tag.lower().startswith("xml"):
        tag = f"col_{tag}"

    return tag


def canonical_header_key(value: str) -> str:
    """Normalize a header name for stylesheet rule matching."""

    return sanitize_xml_tag(value, "col").upper()


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


def rows_to_source_xml(rows: list[list]) -> Element:
    """Serialize raw tabular values and header metadata for XSLT processing."""

    header_row = [source_cell_text(value) for value in rows[0]] if rows else []
    max_columns = max(len(header_row), max((len(row) for row in rows), default=0))
    column_tags = build_column_tags(header_row, max_columns)

    source_root = Element("source")
    columns_element = SubElement(source_root, "columns")
    for column_index, tag_name in enumerate(column_tags):
        header_value = header_row[column_index] if column_index < len(header_row) else ""
        column_element = SubElement(
            columns_element,
            "column",
            index=str(column_index),
            key=canonical_header_key(header_value),
            tag=tag_name,
        )
        column_element.text = header_value

    rows_element = SubElement(source_root, "rows")
    for row_index, row in enumerate(rows[1:], start=2):
        row_element = SubElement(rows_element, "row", index=str(row_index))
        for column_index, tag_name in enumerate(column_tags):
            value = row[column_index] if column_index < len(row) else ""
            cell_element = SubElement(
                row_element,
                "cell",
                index=str(column_index),
                key=canonical_header_key(header_row[column_index] if column_index < len(header_row) else ""),
                tag=tag_name,
            )
            cell_element.text = source_cell_text(value)

    return source_root


def worksheet_to_source_xml(worksheet) -> Element:
    rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
    while rows and not any(value is not None for value in rows[-1]):
        rows.pop()
    return rows_to_source_xml(rows)


def single_row_source(source_root: Element, sample_row: int | None) -> Element | None:
    """Copy the source tree keeping one row: the given sheet row index, or the first row."""

    rows_element = source_root.find("rows")
    if rows_element is None:
        return None
    rows = rows_element.findall("row")
    if sample_row is None:
        selected = rows[0] if rows else None
    else:
        selected = next((row for row in rows if row.get("index") == str(sample_row)), None)
    if selected is None:
        return None

    sample_root = copy.deepcopy(source_root)
    sample_rows = sample_root.find("rows")
    for row in list(sample_rows):
        if row.get("index") != selected.get("index"):
            sample_rows.remove(row)
    return sample_root
