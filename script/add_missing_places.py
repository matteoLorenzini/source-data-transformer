"""Add places from a source XML to an existing CIDOC-CRM RDF file.

Each <place> in the source XML is reconciled with an existing E53_Place (or site)
either through a mapping file or by matching its English or Italian label. Places
that are not found are added as new E53_Place entities, with English and Italian
appellations and coordinates from a local GeoNames dump.

Usage:
    add_missing_places.py --rdf E53_new.rdf --places places.xml --geonames allCountries.txt
        --reconcile config/place_reconciliation.yaml --out E53_new_with_places.rdf
"""

from __future__ import annotations

import argparse
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

import yaml
from lxml import etree
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from transformer.rdf_mapper import NESTING_DEPTH, RDF_ROOT

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
LYNX = Namespace("http://www.lynx.com/resource/")
DEFAULT_MODEL = "Helsinki-NLP/opus-mt-en-it"

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourcePlace:
    place_id: str
    name: str


@dataclass(frozen=True)
class GeoMatch:
    geonames_id: str
    name: str
    country: str
    point: str  # WKT in CRM form: POINT(lon lat)


@dataclass
class Resolution:
    place: SourcePlace
    italian: str
    entity: URIRef
    is_new: bool


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("’", "'"))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def read_places(path: Path) -> list[SourcePlace]:
    root = etree.parse(str(path)).getroot()
    places = []
    for element in root.iter("place"):
        name = (element.findtext("name") or "").strip()
        if not name:
            LOGGER.warning("Skipping place %r without a name", element.get("id"))
            continue
        places.append(SourcePlace(element.get("id"), name))
    return places


@dataclass(frozen=True)
class Reconciliation:
    targets: dict[str, URIRef]  # source place id -> existing RDF entity
    geonames_ids: dict[str, str]  # source place id -> GeoNames id, when the name is ambiguous


def read_reconciliation(path: Path | None) -> Reconciliation:
    if path is None:
        return Reconciliation({}, {})
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    targets = {place_id: URIRef(target) for place_id, target in (data.get("reconcile") or {}).items()}
    geonames_ids = {place_id: str(geo_id) for place_id, geo_id in (data.get("geonames") or {}).items()}
    return Reconciliation(targets, geonames_ids)


def label_index(graph: Graph) -> dict[str, URIRef]:
    """Map each normalized label of an existing E53_Place to its entity."""
    index: dict[str, URIRef] = {}
    for entity in graph.subjects(RDF.type, CRM.E53_Place):
        for label in entity_labels(graph, entity):
            index.setdefault(normalize(label), entity)
    return index


def entity_labels(graph: Graph, entity: URIRef) -> list[str]:
    labels = []
    for appellation in graph.objects(entity, CRM.P1_is_identified_by):
        for predicate in (SKOS.prefLabel, RDFS.label):
            labels.extend(str(value) for value in graph.objects(appellation, predicate))
    return labels


def italian_name(translate: Callable[[str], str], name: str) -> str:
    """Return the Italian name, or the original name when the model output is not a clean phrase.

    The model appends boilerplate to many proper nouns (e.g. "MarburgCity name (optional...)").
    """
    candidate = translate(name).strip()
    is_boilerplate = candidate.startswith(name) and candidate != name
    if not candidate or is_boilerplate or len(candidate) > 2 * len(name) + 10:
        LOGGER.warning("Keeping %r as Italian name: translation %r is not a clean phrase", name, candidate)
        return name
    return candidate


def find_geonames(path: Path, names: set[str], geonames_ids: set[str]) -> tuple[dict[str, GeoMatch], dict[str, GeoMatch]]:
    """Stream GeoNames; return the best match per name and the match per requested id.

    Primary names beat alternate names, then populated places and countries beat other
    features, then larger population wins.
    """
    wanted = {normalize(name): name for name in names}
    prefilter = [name.lower() for name in names]
    best: dict[str, tuple[tuple, GeoMatch]] = {}
    by_id: dict[str, GeoMatch] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            lowered = line.lower()
            if not any(term in lowered for term in prefilter) and line.split("\t", 1)[0] not in geonames_ids:
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 15:
                continue
            match = GeoMatch(cols[0], cols[1], cols[8], f"POINT({cols[5]} {cols[4]})")
            if cols[0] in geonames_ids:
                by_id[cols[0]] = match
            primary = {normalize(cols[1]), normalize(cols[2])}
            alternates = {normalize(alt) for alt in cols[3].split(",")} if cols[3] else set()
            feature_rank = 0 if cols[6] in {"P", "A"} else 1
            population = int(cols[14] or 0)
            for key in wanted.keys() & (primary | alternates):
                tier = 0 if key in primary else 1
                rank = (tier, feature_rank, -population)
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, match)
    return {wanted[key]: match for key, (_, match) in best.items()}, by_id


def has_label(graph: Graph, entity: URIRef, label: str) -> bool:
    return any(normalize(existing) == normalize(label) for existing in entity_labels(graph, entity))


def add_appellation(graph: Graph, entity: URIRef, label: str, lang: str) -> None:
    appellation = URIRef(f"{entity}/{quote(label)}")
    graph.add((entity, CRM.P1_is_identified_by, appellation))
    graph.add((appellation, RDF.type, CRM.E41_Appellation))
    graph.add((appellation, SKOS.prefLabel, Literal(label, lang=lang)))


PLACE_NUMBER = re.compile(r"/place/(\d+)$")


def next_place_number(graph: Graph) -> int:
    """Next free number in the existing place/N URIs, so new places continue the sequence."""
    numbers = [
        int(match.group(1))
        for entity in graph.subjects(RDF.type, CRM.E53_Place)
        if (match := PLACE_NUMBER.search(str(entity)))
    ]
    return max(numbers, default=0) + 1


def resolve(
    graph: Graph,
    place: SourcePlace,
    reconciliation: dict[str, URIRef],
    translate: Callable[[str], str],
    new_entity: URIRef,
) -> Resolution:
    italian = italian_name(translate, place.name)
    if place.place_id in reconciliation:
        return Resolution(place, italian, reconciliation[place.place_id], is_new=False)
    index = label_index(graph)
    for label in (place.name, italian):
        if normalize(label) in index:
            return Resolution(place, italian, index[normalize(label)], is_new=False)
    return Resolution(place, italian, new_entity, is_new=True)


def apply(graph: Graph, resolution: Resolution, geo: GeoMatch | None) -> str:
    place, entity = resolution.place, resolution.entity
    if resolution.is_new:
        if (entity, RDF.type, CRM.E53_Place) not in graph:
            graph.add((entity, RDF.type, CRM.E53_Place))
            place_type = LYNX["place/place"]
            graph.add((entity, CRM.P2_has_type, place_type))
            graph.add((place_type, RDF.type, CRM.E55_Type))
    elif (entity, RDF.type, CRM.E53_Place) not in graph:
        raise ValueError(f"Reconciliation target {entity} is not an E53_Place in the RDF")

    if not has_label(graph, entity, place.name):
        add_appellation(graph, entity, place.name, "en")
    if not has_label(graph, entity, resolution.italian):
        add_appellation(graph, entity, resolution.italian, "it")

    if geo and (entity, CRM.P168_place_is_defined_by, None) not in graph:
        graph.add((entity, CRM.P168_place_is_defined_by, Literal(geo.point)))

    if resolution.is_new:
        return "added"
    return "reconciled"


def add_places(
    graph: Graph,
    places: list[SourcePlace],
    reconciliation: Reconciliation,
    geonames_path: Path,
    translate: Callable[[str], str],
) -> list[tuple[SourcePlace, str, GeoMatch | None, URIRef]]:
    resolutions = []
    number = next_place_number(graph)
    for place in places:
        res = resolve(graph, place, reconciliation.targets, translate, LYNX[f"place/{number}"])
        if res.is_new:
            number += 1
        resolutions.append(res)
    needs_geo = [
        res for res in resolutions if (res.entity, CRM.P168_place_is_defined_by, None) not in graph
    ]
    by_name, by_id = find_geonames(
        geonames_path,
        {res.place.name for res in needs_geo},
        set(reconciliation.geonames_ids.values()),
    ) if needs_geo else ({}, {})
    results = []
    for res in resolutions:
        geo_id = reconciliation.geonames_ids.get(res.place.place_id)
        geo = by_id.get(geo_id) if geo_id else by_name.get(res.place.name)
        if (res.entity, CRM.P168_place_is_defined_by, None) not in graph and geo is None:
            LOGGER.warning("No GeoNames match for %r", res.place.name)
        status = apply(graph, res, geo)
        results.append((res.place, status, geo, res.entity))
    return results


def normalize_timeline(
    graph: Graph, results: list[tuple[SourcePlace, str, GeoMatch | None, URIRef]]
) -> None:
    targets: dict[URIRef, URIRef] = {}
    for place, _, _, entity in results:
        if not place.place_id:
            raise ValueError(f"Source place {place.name!r} has no id")
        source = LYNX[f"place/{quote(place.place_id.strip(), safe='/-._~')}"]
        if source in targets and targets[source] != entity:
            raise ValueError(f"Source place {source} resolves to multiple entities")
        targets[source] = entity

    resolved_entities = set(targets.values())
    replacements = {}
    for place in set(graph.objects(None, CRM.P7_took_place_at)):
        if place in targets:
            if place != targets[place]:
                replacements[place] = targets[place]
        elif place not in resolved_entities:
            LOGGER.warning("No places pipeline match for timeline place %s", place)

    triples = list(graph)
    for subject, predicate, obj in triples:
        if subject in replacements or obj in replacements:
            graph.remove((subject, predicate, obj))
    for subject, predicate, obj in triples:
        if subject in replacements or obj in replacements:
            graph.add((replacements.get(subject, subject), predicate, replacements.get(obj, obj)))


class Translator:
    """Lazily loaded English-to-Italian Marian model."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._tokenizer = None
        self._model = None

    def __call__(self, text: str) -> str:
        if self._model is None:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
        batch = self._tokenizer([text], return_tensors="pt")
        output = self._model.generate(**batch, max_new_tokens=48)
        return self._tokenizer.decode(output[0], skip_special_tokens=True)


def declare_root_namespaces(document: str, source_rdf: Path) -> str:
    """Declare on <rdf:RDF> every namespace of the source file, as 3M does, not only those in use."""
    namespaces = {prefix: uri for prefix, uri in etree.parse(str(source_rdf)).getroot().nsmap.items() if prefix}
    namespaces.update({prefix: uri for prefix, uri in etree.fromstring(document.encode("utf-8")).nsmap.items() if prefix})
    namespaces.setdefault("rdf", str(RDF))
    declarations = "\n".join(f"    xmlns:{prefix}={quoteattr(uri)}" for prefix, uri in namespaces.items())
    return RDF_ROOT.sub(lambda _: f"<rdf:RDF\n{declarations}>", document, count=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rdf", type=Path, required=True, help="Existing RDF/XML file to extend.")
    parser.add_argument("--places", type=Path, required=True, help="Source places XML.")
    parser.add_argument("--geonames", type=Path, required=True, help="GeoNames allCountries.txt.")
    parser.add_argument("--out", type=Path, required=True, help="Output RDF/XML file.")
    parser.add_argument("--timeline", type=Path, help="Timeline RDF/XML file to normalize.")
    parser.add_argument("--timeline-out", type=Path, help="Output path for normalized timeline RDF/XML.")
    parser.add_argument("--reconcile", type=Path, help="YAML mapping of source place id to existing entity URI.")
    parser.add_argument("--translation-model", default=DEFAULT_MODEL, help="Hugging Face EN-IT model.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.timeline) != bool(args.timeline_out):
        parser.error("--timeline and --timeline-out must be supplied together")
    inputs = [args.timeline, args.rdf, args.places, args.geonames, args.reconcile]
    if args.timeline_out and args.timeline_out.resolve() in {
        path.resolve() for path in [*inputs, args.out] if path is not None
    }:
        parser.error("--timeline-out must differ from the input files and --out")
    if args.timeline and args.out.resolve() == args.timeline.resolve():
        parser.error("--out must differ from --timeline")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    graph = Graph()
    graph.parse(str(args.rdf), format="xml")
    places = read_places(args.places)
    reconciliation = read_reconciliation(args.reconcile)
    results = add_places(graph, places, reconciliation, args.geonames, Translator(args.translation_model))

    if args.timeline:
        timeline = Graph()
        timeline.parse(str(args.timeline), format="xml")
        normalize_timeline(timeline, results)
        timeline_document = timeline.serialize(format="pretty-xml", max_depth=NESTING_DEPTH)

    document = graph.serialize(format="pretty-xml", max_depth=NESTING_DEPTH)
    args.out.write_text(declare_root_namespaces(document, args.rdf), encoding="utf-8", newline="\n")
    if args.timeline:
        args.timeline_out.write_text(timeline_document, encoding="utf-8", newline="\n")
        print(f"Wrote {args.timeline_out}")
    for place, status, geo, _ in results:
        detail = f"{geo.name} ({geo.country}, geonames {geo.geonames_id}) {geo.point}" if geo else "no coordinates"
        print(f"{status:10} {place.place_id:35} {place.name}: {detail}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
