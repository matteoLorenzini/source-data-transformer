#!/usr/bin/env python3
"""
Genera un RDF/XML che collega le immagini locali ai reperti (E18) di ResearchSpace.

Per ogni E18 del file RDF di input:
  1. legge l'identificatore con tipo .../identifier/internal-id (es. SPE_238)
  2. cerca la cartella <images-root>\\<internal-id>\\ (es. C:\\Users\\matte\\SPE_238)
  3. per ogni immagine crea:
        E18 --P70i_is_documented_in--> E31_Document --pico:preview--> EX_File
     con rs:PX_has_file_name = nome file per IIIF  (la struttura letta dal template)
  4. copia le immagini in --out-images con nome  <internal-id>_<nomefile>
     (evita collisioni tra cartelle diverse: Cantaloupe usa il solo nome file)

Uso (PowerShell):
  python images_to_rdf.py --rdf reperti.rdf --images-root C:\\Users\\matte --out-rdf immagini.rdf --out-images C:\\Users\\matte\\iiif_images
"""
import argparse
import shutil
import sys
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

CRM = "http://www.cidoc-crm.org/cidoc-crm/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
INTERNAL_ID_TYPE = "http://www.lynx.com/resource/cultural-heritage-object/identifier/internal-id"
EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

A = lambda ns, n: f"{{{ns}}}{n}"


def read_internal_ids(rdf_path):
    """ritorna {iri_E18: internal_id}"""
    root = ET.parse(rdf_path).getroot()

    # 1) tutti gli E42 descritti (ovunque nel file): iri -> (tipi, label)
    ident = {}
    for e in root.iter(A(CRM, "E42_Identifier")):
        iri = e.get(A(RDF, "about"))
        if not iri:
            continue
        types, label = ident.get(iri, (set(), None))
        for t in e.findall(A(CRM, "P2_has_type")):
            types.add(t.get(A(RDF, "resource")) or
                      next((c.get(A(RDF, "about")) for c in t), None))
        lab = e.find(A(RDFS, "label"))
        if lab is not None and lab.text:
            label = lab.text.strip()
        ident[iri] = (types, label)

    # 2) per ogni E18 cerco gli identificatori collegati
    out = {}
    for e18 in root.findall(A(CRM, "E18_Physical_Thing")):
        iri = e18.get(A(RDF, "about"))
        for p1 in e18.findall(A(CRM, "P1_is_identified_by")):
            ref = p1.get(A(RDF, "resource")) or next(
                (c.get(A(RDF, "about")) for c in p1), None)
            types, label = ident.get(ref, (set(), None))
            if INTERNAL_ID_TYPE in types and label:
                out[iri] = label
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rdf", required=True, help="RDF dei reperti (con gli E18)")
    ap.add_argument("--images-root", required=True, help=r"cartella che contiene le cartelle SPE_xxx, es. C:\Users\matte")
    ap.add_argument("--out-rdf", default="immagini.rdf")
    ap.add_argument("--out-images", default="iiif_images", help="cartella dove copiare le immagini rinominate")
    ap.add_argument("--no-copy", action="store_true", help="non copiare i file, genera solo l'RDF")
    args = ap.parse_args()

    ids = read_internal_ids(args.rdf)
    root = Path(args.images_root)
    out_img = Path(args.out_images)
    if not args.no_copy:
        out_img.mkdir(parents=True, exist_ok=True)

    blocks, n_img, no_folder, no_images = [], 0, [], []
    for iri, sid in sorted(ids.items()):
        folder = root / sid
        if not folder.is_dir():
            no_folder.append((iri, sid))
            continue
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXT)
        if not files:
            no_images.append(sid)
            continue
        docs = []
        for p in files:
            new_name = f"{sid}_{p.name}".replace(" ", "_")
            if not args.no_copy:
                shutil.copy2(p, out_img / new_name)
            doc_iri = f"{iri}/document/{quote(new_name)}"
            file_iri = f"http://www.researchspace.org/resource/EX_File/{quote(new_name)}"
            docs.append(
                f'''  <crm:E31_Document rdf:about="{escape(doc_iri)}">
    <rdfs:label>{escape(new_name)}</rdfs:label>
    <pico:preview>
      <rs:EX_File rdf:about="{escape(file_iri)}">
        <rs:PX_has_file_name>{escape(new_name)}</rs:PX_has_file_name>
      </rs:EX_File>
    </pico:preview>
  </crm:E31_Document>''')
            n_img += 1
        refs = "\n".join(
            f'    <crm:P70i_is_documented_in rdf:resource="{escape(iri)}/document/{quote(f"{sid}_{p.name}".replace(" ", "_"))}"/>'
            for p in files)
        blocks.append(f'  <crm:E18_Physical_Thing rdf:about="{escape(iri)}">\n{refs}\n  </crm:E18_Physical_Thing>')
        blocks.extend(docs)

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
    xmlns:rdf="{RDF}"
    xmlns:rdfs="{RDFS}"
    xmlns:crm="{CRM}"
    xmlns:pico="http://data.cochrane.org/ontologies/pico/"
    xmlns:rs="http://www.researchspace.org/ontology/">
{chr(10).join(blocks)}
</rdf:RDF>
'''
    Path(args.out_rdf).write_text(xml, encoding="utf-8")

    print(f"Reperti con ID interno nel file RDF : {len(ids)}")
    print(f"Immagini mappate                    : {n_img}")
    print(f"RDF scritto in                      : {args.out_rdf}")
    if not args.no_copy:
        print(f"Immagini copiate in                 : {out_img}")
    if no_folder:
        print(f"\nReperti SENZA cartella ({len(no_folder)}):")
        for iri, sid in no_folder[:20]:
            print(f"  {sid}  <- {iri}")
        if len(no_folder) > 20:
            print("  ...")
    if no_images:
        print(f"\nCartelle senza immagini valide ({len(no_images)}): {', '.join(no_images[:20])}")
    # cartelle presenti ma senza reperto nel RDF
    known = set(ids.values())
    orphan = sorted(d.name for d in root.iterdir() if d.is_dir() and d.name.startswith("SPE_") and d.name not in known)
    if orphan:
        print(f"\nCartelle SPE_* senza reperto nel RDF ({len(orphan)}): {', '.join(orphan[:20])}")


if __name__ == "__main__":
    sys.exit(main())