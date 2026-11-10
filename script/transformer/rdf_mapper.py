"""Declarative XML to RDF mapping engine (replaces the 3M/X3ML tool).

A mapping is a YAML file with namespaces, URI generators, and rules. Each rule
selects domain nodes with an absolute XPath, builds an entity for each of them,
and follows links to related entities whose XPaths are relative to the domain
node. The result is an rdflib graph that can be serialized as Turtle, RDF/XML,
N-Triples, N-Quads, or TriG.

Mapping format (see script/mappings/ for complete examples)::

    name: Person
    source: main                 # export it applies to: main, relations, or entities
    default_prefix: lynx         # namespace used for UUID URIs
    namespaces: {crm: "http://www.cidoc-crm.org/cidoc-crm/", lynx: "http://www.lynx.com/resource/"}
    generators:
      lynx_place: {prefix: lynx, pattern: "place/{place_id}"}
      UUID: {kind: uuid}
      URIorUUID: {kind: uri_or_uuid}
    rules:
      - domain: /places/place                   # absolute XPath
        when: {exists: place_id/text()}         # optional: exists, equals, not, and, or
        entity:
          types: [crm:E53_Place]                # rdf:type; rdfs:Literal yields a literal
          uri: {generator: lynx_place, args: {place_id: place_id/text(), kind: {const: place}}}
          label: place_name/text()              # optional rdfs:label
          additional:                           # extra triples from this entity
            - {predicate: crm:P2_has_type, entity: {types: [crm:E55_Type], uri: {...}}}
        links:
          - range: place_name                   # XPath relative to the domain node
            predicate: crm:P1_is_identified_by
            through:                            # optional intermediate entities (relative to the range node)
              - {predicate: crm:P98i_was_born, entity: {...}}
            when: {exists: text()}              # evaluated on the range node
            entity: {...}

An entity is skipped, together with the link that needs it, when one of its
generator arguments is empty. Plain strings in ``args`` are XPaths evaluated on
the current node; ``{const: value}`` is a constant.
"""

from __future__ import annotations

import argparse
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from lxml import etree
from rdflib import RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL

LOGGER = logging.getLogger(__name__)

BUILTIN_NAMESPACES = {"rdf": str(RDF), "rdfs": str(RDFS), "xsd": str(XSD), "owl": str(OWL)}
GENERATOR_KINDS = {"pattern", "uuid", "uri_or_uuid"}
SOURCES = {"main", "relations", "entities"}
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
ABSOLUTE_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S+$")
RDF_FORMATS = {
    "turtle": ("turtle", ".ttl"),
    "ttl": ("turtle", ".ttl"),
    "xml": ("xml", ".rdf"),
    "rdfxml": ("xml", ".rdf"),
    "nt": ("nt", ".nt"),
    "nquads": ("nquads", ".nq"),
    "trig": ("trig", ".trig"),
}


class MappingError(ValueError):
    """The mapping file is invalid."""


@dataclass
class Generator:
    name: str
    kind: str = "pattern"
    pattern: str = ""
    prefix: str | None = None
    uuid: bool = False

    @property
    def placeholders(self) -> list[str]:
        return PLACEHOLDER.findall(self.pattern)


@dataclass
class Mapping:
    name: str
    source: str
    default_prefix: str | None
    namespaces: dict[str, str]
    generators: dict[str, Generator]
    rules: list[dict[str, Any]]
    path: Path | None = None
    _xpaths: dict[str, etree.XPath] = field(default_factory=dict, repr=False)

    def xpath(self, expression: str) -> etree.XPath:
        compiled = self._xpaths.get(expression)
        if compiled is None:
            compiled = self._xpaths[expression] = etree.XPath(expression)
        return compiled

    def expand(self, curie: str) -> URIRef:
        prefix, separator, local = curie.partition(":")
        if not separator or local.startswith("//"):
            return URIRef(curie)
        base = self.namespaces.get(prefix)
        if base is None:
            raise MappingError(f"Unknown namespace prefix {prefix!r} in {curie!r}.")
        return URIRef(base + local)


def load_mapping(mapping_path: Path) -> Mapping:
    """Read and validate a YAML mapping file."""

    import yaml

    try:
        document = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MappingError(f"Invalid YAML in {mapping_path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("rules"), list):
        raise MappingError(f"{mapping_path} must be a YAML object with a 'rules' list.")

    namespaces = {**BUILTIN_NAMESPACES, **(document.get("namespaces") or {})}
    generators = {
        name: parse_generator(name, definition or {}) for name, definition in (document.get("generators") or {}).items()
    }
    source = document.get("source", "main")
    if source not in SOURCES:
        raise MappingError(f"'source' must be one of {sorted(SOURCES)}, not {source!r}.")

    mapping = Mapping(
        name=str(document.get("name") or mapping_path.stem),
        source=source,
        default_prefix=document.get("default_prefix"),
        namespaces=namespaces,
        generators=generators,
        rules=document["rules"],
        path=mapping_path,
    )
    validate_mapping(mapping)
    return mapping


def parse_generator(name: str, definition: dict[str, Any]) -> Generator:
    kind = definition.get("kind", "pattern")
    if kind not in GENERATOR_KINDS:
        raise MappingError(f"Generator {name!r} has unsupported kind {kind!r}.")
    if kind == "pattern" and not definition.get("pattern"):
        raise MappingError(f"Generator {name!r} needs a 'pattern'.")
    return Generator(
        name=name,
        kind=kind,
        pattern=definition.get("pattern", ""),
        prefix=definition.get("prefix"),
        uuid=bool(definition.get("uuid", False)),
    )


def validate_mapping(mapping: Mapping) -> None:
    def check_xpath(expression: Any, where: str) -> None:
        if not isinstance(expression, str) or not expression.strip():
            raise MappingError(f"{where}: expected an XPath string.")
        try:
            mapping.xpath(expression)
        except etree.XPathSyntaxError as exc:
            raise MappingError(f"{where}: invalid XPath {expression!r}: {exc}") from exc

    def check_condition(condition: Any, where: str) -> None:
        if not isinstance(condition, dict) or len(condition) != 1:
            raise MappingError(f"{where}: a condition has exactly one of exists/equals/not/and/or.")
        (operator, operand), = condition.items()
        if operator == "exists":
            check_xpath(operand, where)
        elif operator == "equals":
            if not isinstance(operand, list) or len(operand) != 2:
                raise MappingError(f"{where}: 'equals' takes [xpath, value].")
            check_xpath(operand[0], where)
        elif operator == "not":
            check_condition(operand, where)
        elif operator in {"and", "or"}:
            if not isinstance(operand, list) or not operand:
                raise MappingError(f"{where}: '{operator}' takes a non-empty list.")
            for item in operand:
                check_condition(item, where)
        else:
            raise MappingError(f"{where}: unknown condition operator {operator!r}.")

    def check_entity(entity: Any, where: str) -> None:
        if not isinstance(entity, dict):
            raise MappingError(f"{where}: entity must be an object.")
        for curie in entity.get("types", []):
            mapping.expand(curie)
        uri = entity.get("uri")
        if uri is not None:
            generator = mapping.generators.get(uri.get("generator"))
            if generator is None:
                raise MappingError(f"{where}: generator {uri.get('generator')!r} is not defined.")
            args = uri.get("args") or {}
            for arg_name, arg in args.items():
                if not isinstance(arg, dict):
                    check_xpath(arg, f"{where} arg {arg_name!r}")
            missing = [name for name in generator.placeholders if name not in args]
            if missing:
                raise MappingError(f"{where}: generator {generator.name!r} needs argument(s) {missing}.")
            if generator.kind == "uri_or_uuid" and not args:
                raise MappingError(f"{where}: generator {generator.name!r} needs one argument.")
            if generator.prefix and generator.prefix not in mapping.namespaces:
                raise MappingError(f"{where}: generator prefix {generator.prefix!r} has no namespace.")
            if (generator.kind != "pattern" or generator.uuid) and mapping.default_prefix not in mapping.namespaces:
                raise MappingError(f"{where}: 'default_prefix' is required for UUID generators.")
        elif "rdfs:Literal" in entity.get("types", []):
            raise MappingError(f"{where}: a literal entity needs a 'uri' generator for its value.")
        if "label" in entity:
            check_xpath(entity["label"], f"{where} label")
        for extra in entity.get("additional", []):
            mapping.expand(extra["predicate"])
            check_entity(extra["entity"], f"{where} additional")

    for index, rule in enumerate(mapping.rules, start=1):
        where = f"rule {index} ({rule.get('domain')})"
        check_xpath(rule.get("domain"), where)
        if "when" in rule:
            check_condition(rule["when"], where)
        check_entity(rule.get("entity"), where)
        for link in rule.get("links", []):
            link_where = f"{where} link {link.get('range')}"
            check_xpath(link.get("range"), link_where)
            mapping.expand(link["predicate"])
            if "when" in link:
                check_condition(link["when"], link_where)
            for hop in link.get("through", []):
                mapping.expand(hop["predicate"])
                check_entity(hop["entity"], link_where)
            check_entity(link.get("entity"), link_where)


def encode_segment(value: str) -> str:
    return quote(re.sub(r"\s+", "_", value.strip()), safe="-._~")


class Transformer:
    """Apply one mapping to one XML tree, adding triples to a graph."""

    def __init__(self, mapping: Mapping, graph: Graph, salt: str = ""):
        self.mapping = mapping
        self.graph = graph
        self.salt = salt
        self.entities_created = 0
        self.entities_skipped = 0

    def run(self, tree: etree._ElementTree) -> None:
        for rule in self.mapping.rules:
            for domain_node in self.select(tree, rule["domain"]):
                self.apply_rule(rule, domain_node)

    def select(self, node: Any, expression: str) -> list[Any]:
        result = self.mapping.xpath(expression)(node)
        return result if isinstance(result, list) else [result]

    def value(self, node: Any, expression: str) -> str | None:
        result = self.mapping.xpath(expression)(node)
        if isinstance(result, list):
            if not result:
                return None
            result = result[0]
        if isinstance(result, etree._Element):
            result = "".join(result.itertext())
        text = str(result).strip()
        return text or None

    def holds(self, node: Any, condition: dict[str, Any]) -> bool:
        (operator, operand), = condition.items()
        if operator == "exists":
            return self.value(node, operand) is not None
        if operator == "equals":
            return self.value(node, operand[0]) == str(operand[1])
        if operator == "not":
            return not self.holds(node, operand)
        if operator == "and":
            return all(self.holds(node, item) for item in operand)
        return any(self.holds(node, item) for item in operand)

    def apply_rule(self, rule: dict[str, Any], domain_node: Any) -> None:
        if "when" in rule and not self.holds(domain_node, rule["when"]):
            return
        subject = self.build_entity(rule["entity"], domain_node)
        if subject is None:
            return
        for link in rule.get("links", []):
            for range_node in self.select(domain_node, link["range"]):
                self.apply_link(link, subject, range_node)

    def apply_link(self, link: dict[str, Any], subject: Any, range_node: Any) -> None:
        if "when" in link and not self.holds(range_node, link["when"]):
            return
        target = self.build_entity(link["entity"], range_node)
        if target is None:
            return
        chain = []
        for hop in link.get("through", []):
            intermediate = self.build_entity(hop["entity"], range_node)
            if intermediate is None:
                return
            chain.append((self.mapping.expand(hop["predicate"]), intermediate))
        for predicate, intermediate in chain:
            self.graph.add((subject, predicate, intermediate))
            subject = intermediate
        self.graph.add((subject, self.mapping.expand(link["predicate"]), target))

    def build_entity(self, entity: dict[str, Any], node: Any) -> URIRef | BNode | Literal | None:
        types = entity.get("types", [])
        is_literal = "rdfs:Literal" in types
        term = self.generate_term(entity.get("uri"), node, types, is_literal)
        if term is None:
            self.entities_skipped += 1
            return None
        self.entities_created += 1

        if not is_literal:
            for curie in types:
                self.graph.add((term, RDF.type, self.mapping.expand(curie)))
            if "label" in entity:
                label = self.value(node, entity["label"])
                if label is not None:
                    self.graph.add((term, RDFS.label, Literal(label)))
        for extra in entity.get("additional", []):
            related = self.build_entity(extra["entity"], node)
            if related is not None and not is_literal:
                self.graph.add((term, self.mapping.expand(extra["predicate"]), related))
        return term

    def generate_term(
        self, uri: dict[str, Any] | None, node: Any, types: list[str], is_literal: bool
    ) -> URIRef | BNode | Literal | None:
        if uri is None:
            return BNode()

        generator = self.mapping.generators[uri["generator"]]
        arguments: dict[str, str] = {}
        for name, definition in (uri.get("args") or {}).items():
            value = definition["const"] if isinstance(definition, dict) else self.value(node, definition)
            if value is None:
                return None
            arguments[name] = str(value)

        if generator.kind == "uuid":
            return self.uuid_uri(f"{generator.name}|{self.node_key(node)}|{','.join(types)}", salted=True)
        if generator.kind == "uri_or_uuid":
            text = next(iter(arguments.values()))
            return URIRef(text) if ABSOLUTE_URI.match(text) else self.uuid_uri(f"{generator.name}|{text}")

        if is_literal:
            return Literal(PLACEHOLDER.sub(lambda match: arguments[match.group(1)], generator.pattern).strip())

        path = PLACEHOLDER.sub(lambda match: encode_segment(arguments[match.group(1)]), generator.pattern)
        if generator.uuid:
            return self.uuid_uri(f"{generator.name}|{path}")
        if generator.prefix:
            return URIRef(self.mapping.namespaces[generator.prefix] + path)
        return URIRef(path)

    def node_key(self, node: Any) -> str:
        return node.getroottree().getpath(node)

    def uuid_uri(self, key: str, salted: bool = False) -> URIRef:
        # Node-position UUIDs are salted per source file; content-derived ones are shared across files.
        if salted:
            key = f"{self.salt}|{key}"
        namespace = self.mapping.namespaces[self.mapping.default_prefix]
        return URIRef(f"{namespace}{uuid.uuid5(uuid.NAMESPACE_URL, key)}")


def parse_xml(xml_path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        return etree.parse(str(xml_path), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise ValueError(f"Could not read XML {xml_path}: {exc}") from exc


def new_graph(mappings: Iterable[Mapping] = ()) -> Graph:
    graph = Graph()
    for prefix, uri in BUILTIN_NAMESPACES.items():
        graph.bind(prefix, Namespace(uri))
    for mapping in mappings:
        for prefix, uri in mapping.namespaces.items():
            graph.bind(prefix, Namespace(uri), override=False)
    return graph


def transform_tree(mapping: Mapping, tree: etree._ElementTree, graph: Graph | None = None, salt: str = "") -> Graph:
    """Apply a mapping to a parsed XML tree and return the (possibly shared) graph."""

    graph = graph if graph is not None else new_graph([mapping])
    transformer = Transformer(mapping, graph, salt)
    transformer.run(tree)
    LOGGER.info(
        "%s: %d entities created, %d skipped for empty arguments",
        mapping.name,
        transformer.entities_created,
        transformer.entities_skipped,
    )
    return graph


def serialization_format(name: str) -> tuple[str, str]:
    try:
        return RDF_FORMATS[name.lower()]
    except KeyError:
        raise ValueError(f"Unsupported RDF format {name!r}; use one of {sorted(RDF_FORMATS)}.") from None


def write_rdf(
    mapping: Mapping, xml_path: Path, output_path: Path, rdf_format: str = "turtle", salt: str | None = None
) -> int:
    """Transform an XML file with a mapping and write the RDF; return the triple count."""

    format_name, _ = serialization_format(rdf_format)
    graph = transform_tree(mapping, parse_xml(xml_path), salt=xml_path.stem if salt is None else salt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(output_path), format=format_name, encoding="utf-8")
    return len(graph)


def rdf_output_path(xml_path: Path, mapping: Mapping, rdf_format: str) -> Path:
    suffix = serialization_format(rdf_format)[1]
    return xml_path.with_name(f"{xml_path.stem}_{mapping.path.stem if mapping.path else mapping.name}{suffix}")


def source_xml_path(xml_path: Path, source: str) -> Path:
    """Locate the export a mapping applies to, given the main worksheet XML path."""

    if source == "main":
        return xml_path
    return xml_path.with_name(f"{xml_path.stem}_{source}{xml_path.suffix}")


def export_rdf(mapping: Mapping, xml_path: Path, rdf_format: str) -> None:
    """Pipeline step: write the RDF for one mapping next to the worksheet exports."""

    source_path = source_xml_path(xml_path, mapping.source)
    if not source_path.is_file():
        print(f"Skipping mapping {mapping.name}: {source_path.name} was not exported.")
        return
    output_path = rdf_output_path(source_path, mapping, rdf_format)
    print(f"Writing RDF to {output_path}...")
    write_rdf(mapping, source_path, output_path, rdf_format)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transform an XML file to RDF with a YAML mapping.")
    parser.add_argument("--mapping", type=Path, required=True, help="YAML mapping file.")
    parser.add_argument("--xml", type=Path, required=True, help="Source XML file.")
    parser.add_argument("--out", type=Path, help="Output file; defaults to <xml>_<mapping>.<ext>.")
    parser.add_argument("--format", default="turtle", choices=sorted(RDF_FORMATS), help="RDF serialization.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        mapping = load_mapping(args.mapping)
        output_path = args.out or rdf_output_path(args.xml, mapping, args.format)
        triple_count = write_rdf(mapping, args.xml, output_path, args.format)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote {triple_count} triples to {output_path}")
    return 0
