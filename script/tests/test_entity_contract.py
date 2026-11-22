import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transformer.entities import attach_entities, item_key, load_store
from transformer.entity_tables import build_entity_tables
from transformer.source_xml import rows_to_source_xml

TEXT = " <!--td {x}-->Ada\xa0graduated in 1956. "
KEY = "d1923c2ad7533d8e4dd515fa834177bb1143b7f849da614132a984a2dcefd53e"


class EntityContractTests(unittest.TestCase):
    def test_load_and_attach_extraction_store(self):
        self.assertEqual(KEY, item_key("BIOGRAPHY", TEXT))
        store = {
            "version": 1,
            "model": "gliner:test",
            "items": {
                KEY: {
                    "field": "BIOGRAPHY",
                    "subject": "Ada",
                    "entities": [
                        {"type": "event", "value": "Graduation", "context": "Ada graduated in 1956.",
                         "date": "1956", "participants": ["Friedrich Matz"]},
                    ],
                },
            },
        }
        source = rows_to_source_xml([["Unique_ID", "Biography"], ["P_1", TEXT], ["P_2", "Other"]])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entities.json"
            path.write_text(json.dumps(store), encoding="utf-8")
            self.assertEqual(1, attach_entities(source, load_store(path)))

        tables = build_entity_tables(source)
        self.assertEqual(1, len(tables.findall("row")))
        self.assertEqual("P_1", tables.findtext("row/Unique_ID"))
        self.assertEqual("Graduation", tables.findtext("row/Events/Event/Label"))
        self.assertEqual("1956", tables.findtext("row/Events/Event/From"))
        self.assertEqual("Friedrich Matz", tables.findtext("row/Persons/Person/Name"))


if __name__ == "__main__":
    unittest.main()
