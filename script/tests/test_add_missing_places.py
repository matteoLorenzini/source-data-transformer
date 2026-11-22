import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

from add_missing_places import (
    CRM,
    LYNX,
    Reconciliation,
    SourcePlace,
    add_places,
    find_geonames,
    italian_name,
)

GEONAMES_ROWS = [
    # id, name, asciiname, alternatenames, lat, lon, class, code, country, admin1, admin2, admin3, admin4, pop(14)
    "1\tRome\tRome\t\t43.2\t-75.4\tP\tPPL\tUS\t\t\t\t\t\t36",
    "2\tRome\tRome\t\t41.89193\t12.51133\tP\tPPLC\tIT\t\t\t\t\t\t2870000",
    "3\tItalian Republic\tItalian Republic\tItaly,Italia\t42.83\t12.83\tA\tPCLI\tIT\t\t\t\t\t\t58000000",
    "4\tItaly\tItaly\t\t32.18\t-96.88\tP\tPPL\tUS\t\t\t\t\t\t1897",
]


def write_geonames(directory: str) -> Path:
    path = Path(directory) / "geonames.txt"
    rows = [row.split("\t") for row in GEONAMES_ROWS]
    lines = ["\t".join(cols + ["0"] * (15 - len(cols))) for cols in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def fake_translate(text: str) -> str:
    return {"Rome": "Roma", "Italy": "Italia"}.get(text, text + "City name (optional)")


class PlacesTests(unittest.TestCase):
    def test_italian_name_falls_back_when_model_output_is_boilerplate(self):
        self.assertEqual(italian_name(fake_translate, "Marburg"), "Marburg")
        self.assertEqual(italian_name(fake_translate, "Rome"), "Roma")

    def test_geonames_prefers_primary_name_then_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            by_name, by_id = find_geonames(write_geonames(tmp), {"Rome", "Italy"}, {"3"})
        self.assertEqual(by_name["Rome"].geonames_id, "2")
        self.assertEqual(by_name["Rome"].point, "POINT(12.51133 41.89193)")
        self.assertEqual(by_id["3"].point, "POINT(12.83 42.83)")

    def test_add_places_adds_new_place_and_is_idempotent(self):
        graph = Graph()
        graph.bind("crm", CRM)
        places = [SourcePlace("rome", "Rome")]
        with tempfile.TemporaryDirectory() as tmp:
            geonames = write_geonames(tmp)
            add_places(graph, places, Reconciliation({}, {}), geonames, fake_translate)
            first = len(graph)
            add_places(graph, places, Reconciliation({}, {}), geonames, fake_translate)
        entity = LYNX["place/rome"]
        self.assertEqual(len(graph), first)
        self.assertIn((entity, RDF.type, CRM.E53_Place), graph)
        self.assertEqual(len(list(graph.objects(entity, CRM.P168_place_is_defined_by))), 1)

    def test_reconciled_place_gets_names_but_no_new_entity(self):
        site = URIRef("http://www.lynx.com/resource/site/1")
        graph = Graph()
        graph.add((site, RDF.type, CRM.E53_Place))
        target = {"tiberius": site}
        with tempfile.TemporaryDirectory() as tmp:
            add_places(graph, [SourcePlace("tiberius", "Tiberius's Villa")], Reconciliation(target, {}),
                       write_geonames(tmp), lambda text: "Villa di Tiberio")
        self.assertNotIn((LYNX["place/tiberius"], RDF.type, CRM.E53_Place), graph)
        labels = {
            str(label)
            for appellation in graph.objects(site, CRM.P1_is_identified_by)
            for label in graph.objects(appellation, SKOS.prefLabel)
        }
        self.assertIn("Tiberius's Villa", labels)
        self.assertIn("Villa di Tiberio", labels)


if __name__ == "__main__":
    unittest.main()
