import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, SKOS

from add_missing_places import (
    CRM,
    LYNX,
    Reconciliation,
    SourcePlace,
    add_places,
    find_geonames,
    italian_name,
    main,
    normalize_timeline,
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
        graph.add((LYNX["place/3"], RDF.type, CRM.E53_Place))
        places = [SourcePlace("rome", "Rome")]
        with tempfile.TemporaryDirectory() as tmp:
            geonames = write_geonames(tmp)
            add_places(graph, places, Reconciliation({}, {}), geonames, fake_translate)
            first = len(graph)
            add_places(graph, places, Reconciliation({}, {}), geonames, fake_translate)
        entity = LYNX["place/4"]
        self.assertEqual(len(graph), first)
        self.assertIn((entity, RDF.type, CRM.E53_Place), graph)
        self.assertNotIn((LYNX["place/rome"], RDF.type, CRM.E53_Place), graph)
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

    def test_timeline_rewrites_encoded_ids_in_all_references(self):
        source = LYNX["place/s%C3%A3o%20paulo"]
        target = LYNX["place/7"]
        event = LYNX["person/1/activity/1"]
        graph = Graph()
        graph.add((event, CRM.P7_took_place_at, source))
        graph.add((event, CRM.P67_refers_to, source))
        graph.add((source, RDFS.label, Literal("São Paulo")))
        results = [(SourcePlace("são paulo", "São Paulo"), "added", None, target)]
        normalize_timeline(graph, results)
        self.assertIn((event, CRM.P7_took_place_at, target), graph)
        self.assertIn((event, CRM.P67_refers_to, target), graph)
        self.assertIn((target, RDFS.label, Literal("São Paulo")), graph)
        self.assertNotIn((source, None, None), graph)

    def test_pipeline_normalizes_timeline_with_actual_resolutions(self):
        site = LYNX["site/1"]
        event = LYNX["person/1/activity/1"]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "places.rdf"
            places = directory / "places.xml"
            timeline = directory / "timeline.rdf"
            output = directory / "places_out.rdf"
            timeline_output = directory / "timeline_out.rdf"
            graph = Graph()
            graph.add((LYNX["place/6"], RDF.type, CRM.E53_Place))
            graph.add((LYNX["place/6"], CRM.P1_is_identified_by, LYNX["place/6/Rome"]))
            graph.add((LYNX["place/6/Rome"], SKOS.prefLabel, Literal("Rome", lang="en")))
            graph.add((site, RDF.type, CRM.E53_Place))
            graph.serialize(destination=source, format="xml")
            places.write_text(
                '<places><place id="bochum"><name>Bochum</name></place>'
                '<place id="villa"><name>Villa</name></place>'
                '<place id="rome"><name>Rome</name></place></places>', encoding="utf-8"
            )
            config = directory / "reconcile.yaml"
            config.write_text(f"reconcile:\n  villa: {site}\n", encoding="utf-8")
            graph = Graph()
            for place_id, label in (("bochum", "Bochum"), ("villa", "Villa"),
                                    ("rome", "Rome"), ("unknown", "Unknown")):
                place = LYNX[f"place/{place_id}"]
                graph.add((event, CRM.P7_took_place_at, place))
                graph.add((place, RDF.type, CRM.E53_Place))
                graph.add((place, RDFS.label, Literal(label)))
            graph.serialize(destination=timeline, format="xml")
            original = timeline.read_bytes()
            args = [
                "--rdf", str(source), "--places", str(places), "--geonames", str(write_geonames(tmp)),
                "--reconcile", str(config), "--out", str(output),
                "--timeline", str(timeline), "--timeline-out", str(timeline_output),
            ]
            with patch("add_missing_places.Translator", return_value=lambda text: text):
                with self.assertLogs("add_missing_places", level="WARNING") as logs:
                    self.assertEqual(main(args), 0)
            self.assertTrue(any("timeline place http://www.lynx.com/resource/place/unknown" in msg
                                for msg in logs.output))
            self.assertEqual(timeline.read_bytes(), original)
            result = Graph().parse(timeline_output, format="xml")
            place_graph = Graph().parse(output, format="xml")
            self.assertIn((LYNX["place/7"], RDF.type, CRM.E53_Place), place_graph)
            for entity, label in ((LYNX["place/7"], "Bochum"), (site, "Villa"), (LYNX["place/6"], "Rome"),
                                  (LYNX["place/unknown"], "Unknown")):
                self.assertIn((event, CRM.P7_took_place_at, entity), result)
                self.assertIn((entity, RDFS.label, Literal(label)), result)
            self.assertNotIn((None, None, LYNX["place/bochum"]), result)
            self.assertNotIn((LYNX["place/bochum"], None, None), result)

            second_timeline = directory / "timeline_again.rdf"
            args = [
                "--rdf", str(output), "--places", str(places), "--geonames", str(write_geonames(tmp)),
                "--reconcile", str(config), "--out", str(directory / "places_again.rdf"),
                "--timeline", str(timeline_output), "--timeline-out", str(second_timeline),
            ]
            with patch("add_missing_places.Translator", return_value=lambda text: text):
                self.assertEqual(main(args), 0)
            self.assertTrue(isomorphic(result, Graph().parse(second_timeline, format="xml")))


if __name__ == "__main__":
    unittest.main()
