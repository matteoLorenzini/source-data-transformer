"""Entity store: text cleaning, validation, JSON caching, and attachment to the source XML."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement

# Bump when the extraction prompt changes so stale cache entries are not reused.
PROMPT_VERSION = 1

ENTITY_TYPES = ("person", "place", "organization", "date", "role", "work", "event")
OPTIONAL_FIELDS = ("from", "to", "place", "organization", "url")
DATE_PATTERN = re.compile(r"^-?\d{1,4}(-\d{2}(-\d{2})?)?$")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


def clean_text(text: str) -> str:
    """Drop clipboard markup such as <!--td {...}--> and non-breaking spaces."""

    return HTML_COMMENT_PATTERN.sub("", text).replace("\xa0", " ").strip()


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def item_key(field: str, text: str) -> str:
    """Cache key shared by the extraction script and the XML enrichment step."""

    payload = f"{PROMPT_VERSION}\0{field}\0{clean_text(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_store(model: str) -> dict:
    return {"version": 1, "model": model, "items": {}}


def load_store(path: Path) -> dict:
    """Load an entity store from JSON."""

    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid entities JSON in {path}: {exc}") from exc
    if not isinstance(store, dict) or not isinstance(store.get("items"), dict):
        raise ValueError(f"{path} is not an entity store (missing 'items' object).")
    return store


def save_store(path: Path, store: dict) -> None:
    """Write the store atomically so an interrupted run never corrupts the cache."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def validate_entities(raw, text: str) -> tuple[list[dict], int]:
    """Keep well-formed entities whose context is verbatim in the text; return them and the dropped count."""

    if not isinstance(raw, list):
        return [], 0

    haystack = normalize_space(clean_text(text))
    valid: list[dict] = []
    seen: set[tuple] = set()
    dropped = 0

    for candidate in raw:
        if not isinstance(candidate, dict):
            dropped += 1
            continue

        entity_type = str(candidate.get("type", "")).strip().lower()
        value = candidate.get("value")
        context = candidate.get("context")
        if (
            entity_type not in ENTITY_TYPES
            or not isinstance(value, str)
            or not value.strip()
            or not isinstance(context, str)
            or normalize_space(context) not in haystack
        ):
            dropped += 1
            continue

        entity = {"type": entity_type, "value": value.strip(), "context": normalize_space(context)}
        for name in OPTIONAL_FIELDS:
            optional = candidate.get(name)
            if not isinstance(optional, (str, int)) or not str(optional).strip():
                continue
            optional = str(optional).strip()
            if name in ("from", "to") and not DATE_PATTERN.match(optional):
                continue
            if name == "url" and not optional.lower().startswith(("http://", "https://")):
                continue
            entity[name] = optional

        signature = tuple(entity.get(name) for name in ("type", "value", "context", "from", "to"))
        if signature in seen:
            continue
        seen.add(signature)
        valid.append(entity)

    return valid, dropped


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
                attached += 1
    return attached
