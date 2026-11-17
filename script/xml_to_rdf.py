"""Transform an XML file to RDF with a YAML mapping (no 3M/X3ML required).

Usage:
    xml_to_rdf.py --mapping mappings/e53.yaml --xml places_and_sites.xml --out places.ttl
"""

from transformer.rdf_mapper import main

if __name__ == "__main__":
    raise SystemExit(main())
