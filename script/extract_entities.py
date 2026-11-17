"""Extract entities from free-text spreadsheet columns into a reviewable JSON file.

Usage:
    extract_entities.py --file <XLSX> --fields Biography Role Contribution
    extract_entities.py --file <XLSX> --fields Biography --subject-field Name_Surname --dry-run
    extract_entities.py --file <XLSX> --fields Biography Role Contribution --prune

Extraction runs locally with a GLiNER model (transformer/gliner_extractor.py): fast on CPU, no
server and no API key. Install once with: pip install gliner sentencepiece protobuf
Results are cached per cell text, so re-runs only extract new or changed cells; cells extracted
with another model (--gliner-model) are extracted again automatically. Pass the JSON to
download_drive_excel.py with --entities.

Every run also writes a timeline XML, <output stem>_timeline.xml (or --xml-output; --no-xml to
skip), for the rows processed in that run: one <person> per subject with its occupations and a
date-ordered <timeline> of <entry> elements (events, roles, works, birth, death), all with the
same children. See the XML section below for the structure and the intended CIDOC-CRM classes.

Events are found by rules in the cell text (detect_events) and completed with date, place,
organization and participants from the event's own sentence and the other entities of the
same cell (fill_event_from_context); values the text does not support are dropped first
(validate_event). These steps also run on cached cells, so re-running the script fixes
events extracted earlier without extracting again.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook

from transformer.cli import DEFAULT_OUTPUT_DIR
from transformer.entities import (
    clean_text,
    complete_event,
    item_key,
    load_store,
    new_store,
    save_store,
    validate_entities,
)
from transformer.source_xml import canonical_header_key, worksheet_to_source_xml
from transformer.gliner_extractor import PRONOUNS, sentences  # no GLiNER needed at import

# A year (1500-2099) or a decade ("1970s").
YEAR_RE = re.compile(r"\b(?:1[5-9]|20)\d{2}s?\b")
# Words that introduce a location right before a name: "graduated from Marburg", "at Bochum".
PLACE_PREPOSITIONS = ("in", "at", "from", "near")
PLACE_PHRASE_RE = re.compile(r"\b(?:in|at|from|near)\s+([A-Z][\w'’-]*(?:\s+(?:(?:in|of|di|del|della)\s+)?[A-Z][\w'’-]*)*)")


def _anchor(entity: dict) -> int:
    """Position in the context where the event is mentioned (stem match, e.g. 'Graduation' ~ 'graduated')."""

    context = entity.get("context", "").lower()
    value = entity["value"].lower()
    pos = context.find(value)
    if pos < 0:
        stem = value.split()[0][: max(5, len(value.split()[0]) - 4)] if value.split() else ""
        pos = context.find(stem) if stem else -1
    return max(pos, 0)


def _mentions(context: str, names: Iterable[str]) -> list[tuple[int, str]]:
    """(position, name) for every name that occurs in the context, longest names first."""

    found = []
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        pos = context.find(name)
        if pos < 0 or any(start <= pos < start + len(other) for start, other in found):
            continue
        # Skip a name that is only the start of a longer proper name ("Rome" in "Rome Soprintendenza").
        following = re.match(r"\s+([A-Z])", context[pos + len(name):])
        if following:
            continue
        found.append((pos, name))
    return found


def _nearest(mentions: list[tuple[int, str]], anchor: int) -> str | None:
    return min(mentions, key=lambda m: abs(m[0] - anchor))[1] if mentions else None


PROPER_NAME_RE = re.compile(r"^[A-Z][\w'’.-]*(?:\s+(?:(?:in|of|di|del|della|de|von|am)\s+)?[A-Z][\w'’.-]*)*$")


def _known_names(siblings: list[dict]) -> tuple[set[str], set[str], set[str]]:
    """Places, organizations and people extracted from the cell, ignoring events (no self-reinforcement)."""

    others = [e for e in siblings if e.get("type") != "event"]
    places = {e["value"] for e in others if e["type"] == "place"} | {e["place"] for e in others if e.get("place")}
    orgs = {e["value"] for e in others if e["type"] == "organization"}
    orgs |= {e["organization"] for e in others if e.get("organization")}
    people = {e["value"] for e in others if e["type"] == "person" and e["value"].strip().lower() not in PRONOUNS}
    return places, orgs, people


def _plausible(value: str, context: str, known: set[str]) -> bool:
    """A name is kept if it matches an extracted entity, or is a proper name found in the context."""

    if not isinstance(value, str) or not value.strip():
        return False
    value = value.strip()
    if value.lower() in {k.lower() for k in known}:
        return True
    return value in context and bool(PROPER_NAME_RE.match(value))


def validate_event(entity: dict, siblings: list[dict]) -> bool:
    """Drop place, organization and participants of an event that the source does not support.

    Catches model answers like place "Hadrian's Villa and the Baiae" or organization
    "scientific director for underwater research". Dropped fields are refilled by
    fill_event_from_context. Returns True if anything was removed.
    """

    if entity.get("type") != "event":
        return False
    context = entity.get("context", "")
    places, orgs, people = _known_names(siblings)
    removed = False
    if "place" in entity and not _plausible(entity["place"], context, places):
        del entity["place"]
        removed = True
    if "organization" in entity and not _plausible(entity["organization"], context, orgs):
        del entity["organization"]
        removed = True
    if "participants" in entity:
        kept = [p for p in entity["participants"] if _plausible(p, context, people)] if isinstance(entity["participants"], list) else []
        if kept != entity["participants"]:
            removed = True
            if kept:
                entity["participants"] = kept
            else:
                del entity["participants"]
    return removed


def fill_event_from_context(entity: dict, siblings: list[dict]) -> bool:
    """Fill date, place, organization and participants of an event that are still empty.

    Only fields that are missing are set; values already present are never overwritten.
    Every value is taken from the event's context sentence, so nothing is invented.
    """

    if entity.get("type") != "event":
        return False
    context = entity.get("context", "")
    if not context:
        return False
    anchor = _anchor(entity)
    changed = False

    if not entity.get("date") and not entity.get("from"):
        years = [m.group() for m in YEAR_RE.finditer(context)]
        if len(years) == 1:
            entity["date"] = years[0]
            changed = True
        elif years:
            # "In the 1970s and 1980s, ..." -> a span, recorded like the from/to of roles.
            entity["from"], entity["to"] = years[0], years[-1]
            changed = True

    place_names, org_names, person_names = _known_names(siblings)

    if not entity.get("place"):
        # Match places and organizations together so "Rome" inside "Rome Soprintendenza" is not a place.
        known = _mentions(context, place_names | org_names)
        places = [(pos, name) for pos, name in known if name in place_names]
        if not places:
            # A known name used as a location: "graduated from Marburg" (Marburg filed as an organization).
            places = [
                (pos, name)
                for pos, name in known
                if context[:pos].rstrip().split(" ")[-1].lower() in PLACE_PREPOSITIONS
            ]
        if not places:
            # A capitalized name after a preposition: "at Tiberius's Villa in Sperlonga".
            places = [(m.start(1), m.group(1)) for m in PLACE_PHRASE_RE.finditer(context)]
        place = _nearest(places, anchor)
        if place:
            entity["place"] = place
            changed = True

    if not entity.get("organization"):
        orgs = [(pos, name) for pos, name in _mentions(context, org_names) if name != entity.get("place")]
        org = _nearest(orgs, anchor)
        if org:
            entity["organization"] = org
            changed = True

    if not entity.get("participants"):
        people = [name for _, name in sorted(_mentions(context, person_names))]
        if people:
            entity["participants"] = people
            changed = True

    return changed


# Event cues: a word in the text -> the event label written to the JSON. Extend as needed.
EVENT_CUES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgraduat\w*", re.I), "Graduation"),
    (re.compile(r"\bhabilitat\w*", re.I), "Habilitation"),
    (re.compile(r"\b(?:doctorate|Ph\.?D\.?|dissertation)\b", re.I), "Doctorate"),
    (re.compile(r"\b(?:was born|born in|born on)\b", re.I), "Birth"),
    (re.compile(r"\b(?:died|passed away)\b", re.I), "Death"),
    (re.compile(r"\bexcavat\w*", re.I), "Excavation"),
    (re.compile(r"\b(?:surveys?|field campaigns?|campaigns? of)\b", re.I), "Survey"),
    (re.compile(r"\bexpeditions?\b", re.I), "Expedition"),
    (re.compile(r"\bexhibitions?\b", re.I), "Exhibition"),
    (re.compile(r"\b(?:conferences?|congress(?:es)?|symposi(?:um|a))\b", re.I), "Conference"),
    (re.compile(r"\b(?:awarded|prize|medal)\b", re.I), "Award"),
    (re.compile(r"\b(?:married)\b", re.I), "Marriage"),
]


def detect_events(text: str, item: dict) -> int:
    """Add an event for every cue sentence not already covered by an event of the same kind.

    The extractor finds names, not events: "graduated from Marburg in 1956" becomes a Graduation here.
    Added events carry "detected_by": "rule" so they can be told apart when reviewing the JSON.
    """

    existing = {
        (e["value"].lower(), e.get("context", "")) for e in item["entities"] if e["type"] == "event"
    }
    added = 0
    for sentence in sentences(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for pattern, label in EVENT_CUES:
            cue = pattern.search(sentence)
            if not cue:
                continue
            # Skip if an event for this cue already exists in this sentence ("Excavations", "excavations").
            if any(
                value[:5] == label.lower()[:5] and (ctx == sentence or ctx in sentence or sentence in ctx)
                for value, ctx in existing
            ):
                continue
            item["entities"].append(
                {"type": "event", "value": label, "context": sentence, "detected_by": "rule"}
            )
            existing.add((label.lower(), sentence))
            added += 1
    return added


def fill_events(item: dict) -> int:
    """Run the context fallback on every event of a cell; returns how many events changed."""

    changed = 0
    for entity in item["entities"]:
        removed = validate_event(entity, item["entities"])
        if fill_event_from_context(entity, item["entities"]) or removed:
            changed += 1
    return changed


def describe_events(item: dict) -> int:
    """Complete each event of a cell with its date, place, organization and participants."""

    described = 0
    for entity in item["entities"]:
        if entity["type"] != "event":
            continue
        changed = complete_event(entity, None)
        removed = validate_event(entity, item["entities"])
        if fill_event_from_context(entity, item["entities"]) or changed or removed:
            described += 1
    return described


# ---------------------------------------------------------------- XML serialization
# Merges the entities of each subject across fields; see build_timeline() for the XML.

SPAN_YEAR_RE = re.compile(r"^\s*(\d{3,4})(s?)\s*$")


# ---------------------------------------------------------------- helpers

def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def short_hash(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p or "") for p in parts).encode()).hexdigest()[:12]


def year_bounds(value: str | None) -> tuple[str, str] | None:
    """'1956' -> (1956-01-01..., 1956-12-31...); '1970s' -> (1970-01-01..., 1979-12-31...)."""

    match = SPAN_YEAR_RE.match(str(value)) if value else None
    if not match:
        return None
    year = int(match.group(1))
    end = year + 9 if match.group(2) else year
    return f"{year:04d}-01-01", f"{end:04d}-12-31"


def time_span(entity: dict) -> tuple[str | None, str | None, str] | None:
    """(begin, end, label) from date or from/to; end is None for an open span ('from 1978')."""

    if entity.get("date"):
        bounds = year_bounds(entity["date"])
        return (bounds[0], bounds[1], str(entity["date"])) if bounds else None
    start, stop = year_bounds(entity.get("from")), year_bounds(entity.get("to"))
    if not start and not stop:
        return None
    if entity.get("to"):
        label = f"{entity.get('from') or '?'}–{entity['to']}"
    else:
        label = f"from {entity.get('from')}"
    return (start[0] if start else None, stop[1] if stop else None, label)


def location(entity: dict) -> str:
    return (entity.get("place") or entity.get("organization") or "").strip().lower()


def start_key(entity: dict) -> str:
    return str(entity.get("date") or entity.get("from") or "")


def merge(target: dict, other: dict) -> None:
    for key, value in other.items():
        if key == "participants":
            names = list(dict.fromkeys((target.get("participants") or []) + (value or [])))
            if names:
                target["participants"] = names
        elif key == "source_field":
            fields = set(target.get("source_field", "").split()) | set(str(value).split())
            target["source_field"] = " ".join(sorted(fields))
        elif key == "context" and value and len(value) > len(target.get("context", "")):
            target[key] = value
        elif key == "place" and value and target.get(key) and target[key] in value:
            target[key] = value  # keep the fuller name: "Tiberius's Villa" -> "Tiberius's Villa in Sperlonga"
        elif value and not target.get(key):
            target[key] = value


def collect(items: Iterable[dict], default_subject: str | None = None) -> dict[str, dict]:
    """subject -> {"entities": merged events/roles/works, "people": {(name, sentence) or name: relation}}."""

    result: dict[str, dict] = {}
    for item in items:
        subject = (item.get("subject") or default_subject or "").strip()
        if not subject:
            print(f"Skipping in XML (no subject): {item.get('field')} - {item.get('preview')}")
            continue
        record = result.setdefault(subject, {"merged": {}, "people": {}, "subject_id": ""})
        record["subject_id"] = record["subject_id"] or item.get("subject_id", "")
        merged = record["merged"]
        for entity in item["entities"]:
            kind = entity.get("type")
            if kind == "person" and entity.get("relation"):
                record["people"].setdefault((entity["value"], entity.get("context", "")), entity["relation"])
                record["people"].setdefault(entity["value"], entity["relation"])
            if kind not in ("event", "role", "work"):
                continue
            entity = {**entity, "source_field": item.get("field", "")}
            key = (kind, entity["value"].strip().lower(), start_key(entity), location(entity) if kind != "work" else "")
            if key not in merged and kind == "event" and entity.get("context"):
                # Same event type described by the same sentence in two fields: same event.
                same = next(
                    (k for k, e in merged.items() if k[0] == "event" and k[1] == key[1]
                     and (e.get("context") in entity["context"] or entity["context"] in (e.get("context") or "-"))),
                    None,
                )
                if same:
                    merge(merged[same], entity)
                    continue
            if key not in merged and kind != "work":
                # Same name and start, one side without a location: same activity.
                loose = next((k for k in merged if k[:3] == key[:3] and (not k[3] or not key[3])), None)
                if loose:
                    merge(merged[loose], entity)
                    if key[3]:
                        merged[key] = merged.pop(loose)
                    continue
            if key in merged:
                merge(merged[key], entity)
            else:
                merged[key] = entity
    return {
        s: {"entities": list(r["merged"].values()), "people": r["people"], "subject_id": r["subject_id"]}
        for s, r in result.items()
    }


# ---------------------------------------------------------------- XML (one timeline per person)
#
# <persons>
#   <person id="bernard-andreae">                                   E21_Person
#     <unique_id>P_0001</unique_id>                                 Unique_ID of the row (URI person/{Unique_ID})
#     <name>Bernard Andreae</name>                                  P1 E41_Appellation
#     <occupation id="archeologist">Archeologist</occupation>       P2_has_type E55_Type
#     <timeline>
#       <entry id="..." category="event|role|work|birth|death" source_field="BIOGRAPHY">
#         <type id="graduation">Graduation</type>                    P2_has_type E55_Type
#         <label>Graduation at Marburg</label>                        rdfs:label
#         <begin>1956-01-01</begin>                          P4 E52 / P82a_begin_of_the_begin
#         <end>1956-12-31</end>                              P82b_end_of_the_end
#         <date_label>1956</date_label>                               E52 label
#         <place id="marburg">Marburg</place>                         P7_took_place_at E53_Place
#         <organization id="...">...</organization>                   E74_Group
#         <participant id="friedrich-matz" role="teacher">Friedrich Matz</participant>   P11 E21_Person
#         <source_text>...</source_text>                              P3_has_note
#       </entry>
#     </timeline>
#   </person>
# </persons>
#
# Every entry has the same children; only category changes:
#   event        E7_Activity, person P11_had_participant, organization P14_carried_out_by
#   role         E7_Activity, person P14_carried_out_by, organization P11_had_participant
#   work         E65_Creation of an E73_Information_Object (label = title), person P14_carried_out_by
#   birth/death  E67_Birth (P98_brought_into_life) / E69_Death (P100_was_death_of)
# Entries are sorted by date; entries without a date come last. The same place, organization or
# person has the same id everywhere, so a mapping generates one URI for it.


def text_el(parent: ET.Element, tag: str, text: str | None, **attrs: str) -> ET.Element | None:
    if not text:
        return None
    el = ET.SubElement(parent, tag, {k: v for k, v in attrs.items() if v})
    el.text = str(text)
    return el


def _entry_span(entity: dict) -> tuple[str | None, str | None, str] | None:
    if entity["type"] == "work" and not entity.get("to"):
        return time_span({"date": entity.get("date") or entity.get("from")})
    return time_span(entity)


def build_timeline(records: dict[str, dict]) -> ET.Element:
    root = ET.Element("persons")
    for subject, data in records.items():
        person_id = slug(subject)
        person = ET.SubElement(root, "person", {"id": person_id})
        # Unique_ID of the spreadsheet row, so the person gets the same URI as in the Person mapping
        # (person/{Unique_ID}); the name slug when the row has none.
        text_el(person, "unique_id", data.get("subject_id") or person_id)
        text_el(person, "name", subject)
        people = data["people"]

        occupations: list[str] = []
        entries: list[tuple[str, str, dict]] = []
        for entity in data["entities"]:
            kind, value = entity["type"], entity["value"].strip()
            if kind == "role" and not (time_span(entity) or entity.get("place") or entity.get("organization")):
                if value.lower() not in (o.lower() for o in occupations):
                    occupations.append(value)
                continue
            span = _entry_span(entity)
            begin = (span[0] or span[1]) if span else None
            entries.append((begin or "9999", (span[1] or "") if span else "", entity))
        for value in occupations:
            text_el(person, "occupation", value[:1].upper() + value[1:], id=slug(value))

        timeline = ET.SubElement(person, "timeline")
        for _, _, entity in sorted(entries, key=lambda e: (e[0], e[1])):
            kind, value = entity["type"], entity["value"].strip()
            title = value[:1].upper() + value[1:]
            if kind == "event" and value.lower() in ("birth", "death"):
                category = value.lower()
            else:
                category = kind  # event, role, work
            ident = (
                short_hash(subject, "work", value.lower())
                if kind == "work"
                else short_hash(subject, kind, value.lower(), start_key(entity), location(entity))
            )
            entry = ET.SubElement(timeline, "entry", {
                k: v for k, v in {
                    "id": ident,
                    "category": category,
                    "source_field": entity.get("source_field", ""),
                    "detected_by": entity.get("detected_by", ""),
                }.items() if v
            })

            place = entity.get("place")
            org = entity.get("organization")
            if org and org.strip().lower() == (place or "").strip().lower():
                org = None
            if kind == "work":
                text_el(entry, "type", "Publication", id="publication")
                text_el(entry, "label", value)
            else:
                text_el(entry, "type", title, id=slug(value))
                if kind == "event":
                    where = place or org
                else:
                    where = ", ".join(v for v in (org, place) if v)
                text_el(entry, "label", title + (f" at {where}" if where else ""))

            span = _entry_span(entity)
            if span:
                begin, end, label = span
                text_el(entry, "begin", begin)
                text_el(entry, "end", end)
                text_el(entry, "date_label", label)
            if place:
                text_el(entry, "place", place, id=slug(place))
            if org:
                text_el(entry, "organization", org, id=slug(org))
            for name in entity.get("participants") or []:
                if name.strip().lower() == subject.lower() or name.strip().lower() in PRONOUNS:
                    continue
                relation = people.get((name, entity.get("context") or ""), "") or people.get(name, "")
                text_el(entry, "participant", name, id=slug(name), role=relation)
            text_el(entry, "source_text", entity.get("context"))
    return root


def write_entities_xml(items: Iterable[dict], path: Path) -> ET.Element:
    """Write the timeline XML (one <person> with its <timeline> per subject)."""

    root = build_timeline(collect(items))
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract entities from free-text columns of a workbook.")
    parser.add_argument("--file", type=Path, required=True, help="Local .xlsx workbook.")
    parser.add_argument("--sheet-name", help="Process only this worksheet; by default all worksheets.")
    parser.add_argument("--fields", nargs="+", required=True, help="Header names of the free-text columns.")
    parser.add_argument("--subject-field", default="Name_Surname", help="Header of the column naming the record subject.")
    parser.add_argument("--id-field", default="Unique_ID", help="Header of the column with the subject's identifier.")
    parser.add_argument("--output", type=Path, help="Entity JSON path; defaults to output_data/<workbook>_entities.json.")
    parser.add_argument("--gliner-model", default="urchade/gliner_multi-v2.1", help="Hugging Face GLiNER model.")
    parser.add_argument("--threshold", type=float, default=0.4, help="GLiNER confidence threshold (0-1).")
    parser.add_argument("--refresh", action="store_true", help="Re-extract cells that are already cached.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove cached items whose cell text no longer exists in the workbook (old versions of edited cells).",
    )
    parser.add_argument(
        "--xml-output",
        type=Path,
        help="Timeline XML; defaults to <output stem>_timeline.xml next to the JSON. Covers the rows processed in this run.",
    )
    parser.add_argument("--no-xml", action="store_true", help="Write only the JSON, no XML.")
    parser.add_argument("--dry-run", action="store_true", help="List the cells that would be extracted, without loading the model.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    workbook_path = args.file.resolve()
    if not workbook_path.is_file():
        parser.error(f"Workbook does not exist: {workbook_path}")
    if args.prune and args.sheet_name:
        parser.error("--prune needs the whole workbook; drop --sheet-name or run without --prune.")

    output_path = args.output or DEFAULT_OUTPUT_DIR / f"{workbook_path.stem}_entities.json"
    field_keys = [canonical_header_key(name) for name in args.fields]
    subject_key = canonical_header_key(args.subject_field)
    id_key = canonical_header_key(args.id_field)

    workbook = load_workbook(workbook_path, data_only=True)
    if args.sheet_name:
        if args.sheet_name not in workbook.sheetnames:
            parser.error(f"Worksheet {args.sheet_name!r} not found. Available: {', '.join(workbook.sheetnames)}")
        worksheets = [workbook[args.sheet_name]]
    else:
        worksheets = workbook.worksheets

    extractor_name = f"gliner:{args.gliner_model}"
    gliner = None
    if not args.dry_run:
        from transformer.gliner_extractor import GlinerExtractor

        gliner = GlinerExtractor(args.gliner_model, args.threshold)
    store = new_store(extractor_name)
    if output_path.is_file():
        try:
            store = load_store(output_path)
        except ValueError as exc:
            parser.error(str(exc))
    previous_model = store.get("model", "")
    if not args.dry_run:
        store["model"] = extractor_name

    extracted = skipped = dropped_total = described = filled = detected_total = 0
    seen_keys: set[str] = set()
    for worksheet in worksheets:
        for row in worksheet_to_source_xml(worksheet).iter("row"):
            cells = {cell.get("key"): cell.text or "" for cell in row.findall("cell")}
            subject = cells.get(subject_key, "").strip()
            subject_id = re.sub(r"\.0$", "", cells.get(id_key, "").strip())  # 12.0 -> 12 from numeric cells
            for field_key in field_keys:
                text = clean_text(cells.get(field_key, ""))
                if not text:
                    continue
                key = item_key(field_key, text)
                seen_keys.add(key)
                label = f"{worksheet.title} row {row.get('index')} {field_key}"
                item = store["items"].get(key)
                if item is not None and item.get("extractor", previous_model) != extractor_name:
                    item = None  # extracted with another model (or the former Ollama backend): extract again
                if item is not None and not args.refresh:
                    skipped += 1
                    if args.dry_run:
                        continue
                    if subject:
                        item["subject"] = subject
                    if subject_id:
                        item["subject_id"] = subject_id
                    detected_total += detect_events(text, item)
                    filled += fill_events(item)
                    save_store(output_path, store)
                    continue

                if args.dry_run:
                    print(f"Would extract: {label} ({len(text)} chars)")
                    continue

                print(f"Extracting: {label}...")
                raw = gliner.extract(field_key, subject, text)
                entities, dropped = validate_entities(raw, text)
                dropped_total += dropped
                item = store["items"][key] = {
                    "field": field_key,
                    "subject": subject,
                    "subject_id": subject_id,
                    "extractor": extractor_name,
                    "preview": text[:80],
                    "entities": entities,
                }
                detected_total += detect_events(text, item)
                described += describe_events(item)
                save_store(output_path, store)
                extracted += 1

    pruned = 0
    if args.prune:
        stale = [key for key in store["items"] if key not in seen_keys]
        if args.dry_run:
            for key in stale:
                print(f"Would prune: {store['items'][key]['field']} - {store['items'][key]['preview']}")
        else:
            for key in stale:
                del store["items"][key]
            if stale:
                save_store(output_path, store)
        pruned = len(stale)

    print(
        f"Extracted {extracted} cells, reused {skipped} cached, dropped {dropped_total} invalid entities, "
        f"detected {detected_total} events, completed {described} events, "
        f"filled {filled} cached events from context, pruned {pruned} stale items."
    )
    if extracted or filled or pruned or detected_total:
        print(f"Entities written to {output_path}")

    if not args.dry_run and not args.no_xml:
        xml_path = args.xml_output or output_path.with_name(f"{output_path.stem}_timeline.xml")
        root = write_entities_xml((store["items"][key] for key in seen_keys if key in store["items"]), xml_path)
        entries = root.findall("person/timeline/entry")
        counts = {c: sum(1 for e in entries if e.get("category") == c) for c in ("event", "role", "work", "birth", "death")}
        print(f"XML: {len(root)} persons, {len(entries)} timeline entries "
              f"({', '.join(f'{n} {c}' for c, n in counts.items() if n)}) written to {xml_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())