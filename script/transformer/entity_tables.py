"""Build one XML file with the entities of each spreadsheet row, grouped by domain (Places, Roles, ...)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent


def slugify(text: str) -> str:
    """ASCII identifier fragment for a label; falls back to a hash for non-Latin text."""

    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _subject_id(row: Element) -> str:
    for cell in row.findall("cell"):
        if cell.get("key") == "UNIQUE_ID":
            return (cell.text or "").strip()
    return ""


def _named(registry: dict, prefix: str, name: str, mention: tuple, relation: str = "") -> str:
    """Register a place, organization or person once and return its id."""

    record_id = f"{prefix}-{slugify(name)}"
    record = registry.setdefault(record_id, {"name": name.strip(), "mentions": [], "place": "", "links": [], "relations": []})
    if mention not in record["mentions"]:
        record["mentions"].append(mention)
    if relation and relation not in record["relations"]:
        record["relations"].append(relation)
    return record_id


def _link(registry: dict, record_id: str, link: tuple) -> None:
    """Record on a place or organization the role or event that refers to it."""

    if record_id and link not in registry[record_id]["links"]:
        registry[record_id]["links"].append(link)


def build_entity_tables(source_root: Element) -> Element:
    """Return <scheda> with one <row> per source row that has entities."""

    scheda = Element("scheda")
    counters = {"role": 0, "event": 0, "work": 0}
    for row in source_root.iter("row"):
        tables = _row_tables(row, counters)
        if not tables:
            continue
        row_element = SubElement(scheda, "row", index=row.get("index", ""))
        SubElement(row_element, "Unique_ID").text = _subject_id(row)
        for table in tables:
            row_element.append(table)
    return scheda


def _row_tables(row: Element, counters: dict) -> list[Element]:
    """Group the entities of one row by domain; roles, events, and works are numbered across rows."""

    persons: dict = {}
    places: dict = {}
    organizations: dict = {}
    roles: dict = {}
    events: dict = {}
    works: dict = {}
    row_index = row.get("index", "")

    for entities in row.findall("entities"):
        field = entities.get("field", "")
        for entity in entities.findall("entity"):
            kind = entity.get("type")
            value = (entity.findtext("value") or "").strip()
            context = (entity.findtext("context") or "").strip()
            begin = (entity.findtext("from") or "").strip()
            end = (entity.findtext("to") or "").strip()
            place = (entity.findtext("place") or "").strip()
            organization = (entity.findtext("organization") or "").strip()
            url = (entity.findtext("url") or "").strip()
            mention = (row_index, field, context)
            relation = (entity.findtext("relation") or "").strip()

            if kind == "person":
                _named(persons, "person", value, mention, relation)
            elif kind == "place":
                _named(places, "place", value, mention, relation)
            elif kind == "organization":
                organization_id = _named(organizations, "org", value, mention, relation)
                if place:
                    organizations[organization_id]["place"] = _named(places, "place", place, mention)
            elif kind in ("role", "event"):
                place_id = _named(places, "place", place, mention) if place else ""
                organization_id = _named(organizations, "org", organization, mention) if organization else ""
                registry = roles if kind == "role" else events
                key = (slugify(value), organization_id, place_id, begin, end)
                record = registry.get(key)
                if record is None:
                    counters[kind] += 1
                    record = registry[key] = {
                        "id": f"{kind}-{counters[kind]}", "name": value, "row": row_index,
                        "organization": organization_id, "place": place_id,
                        "from": begin, "to": end, "sources": [],
                    }
                if (field, context) not in record["sources"]:
                    record["sources"].append((field, context))
                link = (kind, record["id"], value, begin, end)
                _link(places, place_id, link)
                _link(organizations, organization_id, link)
            elif kind == "work":
                record = works.get(slugify(value))
                if record is None:
                    counters["work"] += 1
                    record = works[slugify(value)] = {
                        "id": f"work-{counters['work']}", "name": value,
                        "from": begin, "to": end, "url": url, "mentions": [], "relations": [],
                    }
                record["url"] = record["url"] or url
                if relation and relation not in record["relations"]:
                    record["relations"].append(relation)
                if mention not in record["mentions"]:
                    record["mentions"].append(mention)

    tables = [
        _shared_table("Persons", "Person", persons),
        _shared_table("Places", "Place", places),
        _shared_table("Organizations", "Organization", organizations),
        _activity_table("Roles", "Role", "role", roles),
        _activity_table("Events", "Event", "event", events),
        _works_table(works),
    ]
    return [table for table in tables if len(table)]


def _text(parent: Element, tag: str, value: str) -> None:
    if value:
        SubElement(parent, tag).text = value


def _ref(parent: Element, tag: str, record_id: str) -> None:
    if record_id:
        SubElement(parent, tag, ref=record_id)


def _mention(parent: Element, mention: tuple) -> None:
    row_index, field, context = mention
    SubElement(parent, "Source", row=row_index, field=field).text = context


def _shared_table(root_tag: str, item_tag: str, registry: dict) -> Element:
    root = Element(root_tag)
    for record_id, record in sorted(registry.items()):
        item = SubElement(root, item_tag, id=record_id)
        _text(item, "Name", record["name"])
        _ref(item, "Place", record["place"])
        for relation in record["relations"]:
            _text(item, "Relation", relation)
        for kind, link_id, label, begin, end in record["links"]:
            link = SubElement(item, kind.capitalize(), ref=link_id)
            _text(link, "Title" if kind == "role" else "Label", label)
            _text(link, "From", begin)
            _text(link, "To", end)
        for mention in record["mentions"]:
            _mention(item, mention)
    return root


def _activity_table(root_tag: str, item_tag: str, prefix: str, registry: dict) -> Element:
    root = Element(root_tag)
    for record in registry.values():
        item = SubElement(root, item_tag, id=record["id"], row=record["row"])
        _text(item, "Title" if prefix == "role" else "Label", record["name"])
        _ref(item, "Organization", record["organization"])
        _ref(item, "Place", record["place"])
        _text(item, "From", record["from"])
        _text(item, "To", record["to"])
        for field, context in record["sources"]:
            SubElement(item, "Source", field=field).text = context
    return root


def _works_table(registry: dict) -> Element:
    root = Element("Works")
    for record in registry.values():
        item = SubElement(root, "Work", id=record["id"])
        _text(item, "Title", record["name"])
        _text(item, "From", record["from"])
        _text(item, "To", record["to"])
        _text(item, "Url", record["url"])
        for relation in record["relations"]:
            _text(item, "Relation", relation)
        for mention in record["mentions"]:
            _mention(item, mention)
    return root


def write_entity_tables(source_root: Element, path: Path) -> bool:
    """Write the per-row entities to one XML file; return False when there are none."""

    scheda = build_entity_tables(source_root)
    if not len(scheda):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    indent(scheda)
    ElementTree(scheda).write(path, encoding="utf-8", xml_declaration=True)
    return True
