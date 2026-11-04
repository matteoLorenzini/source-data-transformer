"""Load XSLT stylesheets and write the CSV, XML, and relation exports they produce."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from xml.etree.ElementTree import Element, tostring

from .source_xml import single_row_source


def load_stylesheet_mapping(mapping_path: Path) -> dict[str, Path]:
    """Load Google Drive file-id to XSLT path mappings from JSON."""

    try:
        configuration = json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid stylesheet mapping JSON in {mapping_path}: {exc}") from exc

    if not isinstance(configuration, dict):
        raise ValueError("The stylesheet mapping must be a JSON object of file IDs to stylesheet paths.")

    mapping: dict[str, Path] = {}
    for file_id, stylesheet in configuration.items():
        if not isinstance(file_id, str) or not isinstance(stylesheet, str) or not stylesheet.strip():
            raise ValueError("Every stylesheet mapping must have a file ID and a non-empty path.")

        stylesheet_path = Path(stylesheet)
        if not stylesheet_path.is_absolute():
            stylesheet_path = mapping_path.parent / stylesheet_path
        mapping[file_id] = stylesheet_path.resolve()

    return mapping


def load_stylesheet(stylesheet_path: Path):
    """Compile an external XSLT stylesheet."""

    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        stylesheet_tree = etree.parse(str(stylesheet_path), parser)
        return etree.XSLT(
            stylesheet_tree,
            access_control=etree.XSLTAccessControl.DENY_ALL,
        )
    except (etree.XMLSyntaxError, etree.XSLTParseError) as exc:
        raise ValueError(f"Could not load XSLT stylesheet {stylesheet_path}: {exc}") from exc


def apply_stylesheet(source_root: Element, stylesheet, output_mode: str):
    """Transform neutral source XML using the selected output mode."""

    from lxml import etree

    source_tree = etree.fromstring(tostring(source_root, encoding="utf-8"))
    try:
        return stylesheet(source_tree, output_mode=etree.XSLT.strparam(output_mode))
    except etree.XSLTApplyError as exc:
        raise ValueError(f"XSLT transformation failed: {exc}") from exc


def write_xslt_xml(result, destination_path: Path) -> None:
    """Write an XSLT XML result, defaulting an unspecified encoding to UTF-8."""

    try:
        result.write_output(str(destination_path))
    except LookupError as exc:
        if str(exc) != "unknown encoding: ''":
            raise
        from lxml import etree

        destination_path.write_bytes(etree.tostring(result, encoding="utf-8", xml_declaration=True))


def fill_missing_sample_relation_values(result) -> None:
    """Add a zero placeholder to empty relation fields in the sample export."""

    from lxml import etree

    for element in result.getroot().xpath(
        "/scheda/row/*[starts-with(local-name(), 'Sequenza_')]"
    ):
        if not element.findall("value"):
            etree.SubElement(element, "value").text = "0000"


def write_source_exports(
    source_root: Element,
    csv_path: Path,
    xml_path: Path,
    stylesheet,
    sample_row: int | None = None,
    include_entities: bool = False,
) -> None:
    """Generate all exported formats through the selected external stylesheet."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.parent.mkdir(parents=True, exist_ok=True)

    csv_result = apply_stylesheet(source_root, stylesheet, "csv")
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        for row_element in csv_result.getroot().findall("row"):
            writer.writerow([
                cell_element.text or ""
                for cell_element in row_element.findall("cell")
            ])

    main_result = apply_stylesheet(source_root, stylesheet, "main")
    write_xslt_xml(main_result, xml_path)

    relation_xml_path = xml_path.with_name(f"{xml_path.stem}_relations{xml_path.suffix}")
    relation_result = apply_stylesheet(source_root, stylesheet, "relations")
    write_xslt_xml(relation_result, relation_xml_path)

    entities_xml_path = xml_path.with_name(f"{xml_path.stem}_entities{xml_path.suffix}")
    if include_entities:
        write_xslt_xml(apply_stylesheet(source_root, stylesheet, "entities"), entities_xml_path)

    sample_root = single_row_source(source_root, sample_row)
    if sample_root is not None:
        sample_xml_path = xml_path.with_name(f"{xml_path.stem}_sample{xml_path.suffix}")
        write_xslt_xml(apply_stylesheet(sample_root, stylesheet, "main"), sample_xml_path)
        if include_entities:
            sample_entities_path = xml_path.with_name(f"{xml_path.stem}_entities_sample{xml_path.suffix}")
            write_xslt_xml(apply_stylesheet(sample_root, stylesheet, "entities"), sample_entities_path)
        sample_relation_xml_path = xml_path.with_name(
            f"{xml_path.stem}_relations_sample{xml_path.suffix}"
        )
        sample_relation_result = apply_stylesheet(sample_root, stylesheet, "relations")
        fill_missing_sample_relation_values(sample_relation_result)
        write_xslt_xml(sample_relation_result, sample_relation_xml_path)
