"""Tests for the YAML XML-to-RDF mapping engine. Run from the script directory: python -m unittest discover -s tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree
from rdflib import RDF, RDFS, Literal, URIRef

from transformer.rdf_mapper import MappingError, load_mapping, new_graph, transform_tree

LYNX = "http://www.lynx.com/resource/"
CRM = "http://www.cidoc-crm.org/cidoc-crm/"

MAPPING = """
name: test
default_prefix: lynx
namespaces: {lynx: "http://www.lynx.com/resource/", crm: "http://www.cidoc-crm.org/cidoc-crm/"}
generators:
  person: {prefix: lynx, pattern: "person/{id}"}
  name: {prefix: lynx, pattern: "person/{id}/{name}"}
  birth: {prefix: lynx, pattern: "person/{id}/birth"}
  place: {prefix: lynx, pattern: "place/{id}"}
  UUID: {kind: uuid}
  URIorUUID: {kind: uri_or_uuid}
rules:
  - domain: /rows/row
    entity:
      types: [crm:E21_Person]
      uri: {generator: person, args: {id: id/text()}}
    links:
      - range: name
        predicate: crm:P1_is_identified_by
        when: {exists: text()}
        entity:
          types: [crm:E41_Appellation]
          uri: {generator: name, args: {id: ../id/text(), name: text()}}
          label: text()
      - range: birth_place
        through:
          - predicate: crm:P98i_was_born
            entity: {types: [crm:E67_Birth], uri: {generator: birth, args: {id: ../id/text()}}}
        predicate: crm:P7_took_place_at
        entity:
          types: [crm:E53_Place]
          uri: {generator: place, args: {id: text()}}
      - range: bio
        predicate: crm:P67i_is_referred_to_by
        entity: {types: [crm:E73_Information_Object], uri: {generator: UUID}}
      - range: same_as
        predicate: crm:P130_shows_features_of
        entity: {types: [crm:E21_Person], uri: {generator: URIorUUID, args: {text: text()}}}
"""

XML = """<rows>
  <row><id>1</id><name>Ada Lovelace</name><birth_place>7</birth_place><bio>Text</bio>
       <same_as>http://example.org/p/9</same_as></row>
  <row><id>2</id><name/><bio>Other</bio></row>
</rows>"""


class RdfMapperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.mapping = self.load(MAPPING)
        self.tree = etree.ElementTree(etree.fromstring(XML))

    def load(self, text):
        path = Path(self.directory.name) / "mapping.yaml"
        path.write_text(text, encoding="utf-8")
        return load_mapping(path)

    def run_mapping(self, salt=""):
        return transform_tree(self.mapping, self.tree, new_graph([self.mapping]), salt)

    def test_entities_labels_and_encoding(self):
        graph = self.run_mapping()
        person = URIRef(LYNX + "person/1")
        appellation = URIRef(LYNX + "person/1/Ada_Lovelace")
        self.assertIn((person, RDF.type, URIRef(CRM + "E21_Person")), graph)
        self.assertIn((person, URIRef(CRM + "P1_is_identified_by"), appellation), graph)
        self.assertIn((appellation, RDFS.label, Literal("Ada Lovelace")), graph)

    def test_condition_and_missing_range_skip_links(self):
        graph = self.run_mapping()
        person_two = URIRef(LYNX + "person/2")
        self.assertEqual([], list(graph.objects(person_two, URIRef(CRM + "P1_is_identified_by"))))
        self.assertEqual([], list(graph.objects(person_two, URIRef(CRM + "P7_took_place_at"))))

    def test_intermediate_entity_chain(self):
        graph = self.run_mapping()
        birth = URIRef(LYNX + "person/1/birth")
        self.assertIn((URIRef(LYNX + "person/1"), URIRef(CRM + "P98i_was_born"), birth), graph)
        self.assertIn((birth, URIRef(CRM + "P7_took_place_at"), URIRef(LYNX + "place/7")), graph)

    def test_uri_or_uuid_keeps_absolute_uris(self):
        graph = self.run_mapping()
        self.assertIn(
            (URIRef(LYNX + "person/1"), URIRef(CRM + "P130_shows_features_of"), URIRef("http://example.org/p/9")),
            graph,
        )

    def test_uuids_are_deterministic_and_salted_per_source(self):
        first = set(self.run_mapping("a").objects(None, URIRef(CRM + "P67i_is_referred_to_by")))
        again = set(self.run_mapping("a").objects(None, URIRef(CRM + "P67i_is_referred_to_by")))
        other = set(self.run_mapping("b").objects(None, URIRef(CRM + "P67i_is_referred_to_by")))
        self.assertEqual(2, len(first))
        self.assertEqual(first, again)
        self.assertTrue(first.isdisjoint(other))

    def test_invalid_mapping_is_rejected(self):
        with self.assertRaises(MappingError):
            self.load(MAPPING.replace("generator: person,", "generator: missing,"))
        with self.assertRaises(MappingError):
            self.load(MAPPING.replace("crm:E41_Appellation", "nope:E41_Appellation"))


class ShippedMappingsTests(unittest.TestCase):
    def test_all_shipped_mappings_load(self):
        mappings = sorted((Path(__file__).resolve().parent.parent / "mappings").glob("*.yaml"))
        self.assertTrue(mappings)
        for path in mappings:
            with self.subTest(path.name):
                load_mapping(path)


if __name__ == "__main__":
    unittest.main()
