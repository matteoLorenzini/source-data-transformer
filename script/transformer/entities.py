"""Load and attach entity-extraction JSON to source XML."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement

# Part of the entity-extraction JSON contract; keep in sync with its producer.
PROMPT_VERSION = 6
OPTIONAL_FIELDS = ("from", "to", "date", "place", "organization", "url", "relation")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


def item_key(field: str, text: str) -> str:
    """Return the versioned cache key for a canonical field name and cell text."""

    text = HTML_COMMENT_PATTERN.sub("", text).replace("\xa0", " ").strip()
    payload = f"{PROMPT_VERSION}\0{field}\0{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_store(path: Path) -> dict:
    """Load an entity store from JSON."""

    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid entities JSON in {path}: {exc}") from exc
    if not isinstance(store, dict) or not isinstance(store.get("items"), dict):
        raise ValueError(f"{path} is not an entity store (missing 'items' object).")
    return store


def attach_entities(source_root: Element, store: dict) -> int:
    """Append <entities> to each source row for cells whose text has cached entities."""

    rows_element = source_root.find("rows")
    if rows_element is None:
        return 0

    attached = 0
    for row in rows_element.findall("row"):
        for cell in row.findall("cell"):
            item = store["items"].get(item_key(cell.get("key", ""), cell.text or ""))
            if not item:
                continue
            entities_element = SubElement(row, "entities", field=cell.get("key", ""))
            for entity in item["entities"]:
                entity_element = SubElement(entities_element, "entity", type=entity["type"])
                for name in ("value", "context", *OPTIONAL_FIELDS):
                    if name in entity:
                        SubElement(entity_element, name).text = entity[name]
                for participant in entity.get("participants", []):
                    SubElement(entity_element, "participant").text = participant
                attached += 1
    return attached
