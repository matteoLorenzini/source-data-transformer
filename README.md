# source-data-transformer

## Project scope

This repository supports a data harmonization workflow for cultural heritage records curated by the Lynx Research Unit at IMT.

The source data are maintained in Google Sheets. The goal of this project is to transform and normalize those tabular records into structured export files that can be used as a preparation step before semantic modeling in CIDOC-CRM.

## Why this exists

Before CIDOC-CRM modeling, source data usually need to be:

- consolidated from spreadsheet structures;
- cleaned and normalized into consistent values;
- exported in machine-readable formats that are easier to validate and map.

This repository covers that pre-modeling stage.

## Workflows

The pipeline runs in four stages. Each stage can be run on its own; the later ones consume the output of the earlier ones.

1. **Spreadsheet export**: download a Google Sheet (or read a local `.xlsx`) and export each worksheet to CSV and XML, normalizing multi-value fields into repeated sub-elements. See [Workflow 1](#workflow-1-spreadsheet-export).
2. **Entity extraction** (optional): add the entities found in free text, produced by the separate [entity-extraction project](https://github.com/matteoLorenzini/entity-extraction). See [Workflow 2](#workflow-2-entity-extraction-optional).
3. **XML to CIDOC-CRM RDF**: map the XML exports to RDF with YAML mapping files. See [Workflow 3](#workflow-3-xml-to-cidoc-crm-rdf).
4. **Places**: add the places missing from the RDF, with English/Italian names and GeoNames coordinates. See [Workflow 4](#workflow-4-places).

Input is read from Google Sheets (public or authenticated access) or from local `.xlsx` workbooks. Default output directory: `script/output_data` (git-ignored).

## Repository layout

```text
script/
  download_drive_excel.py   Entry point, workflow 1 (spreadsheet export)
  xml_to_rdf.py             Entry point, workflow 3 (XML to RDF)
  add_missing_places.py     Entry point, workflow 4 (places)
  transformer/              Implementation package (see Code layout)
  xslt/                     XSLT stylesheets used by workflow 1
  mappings/                 YAML XML-to-CIDOC-CRM mappings used by workflow 3
  config/                   Place reconciliation and GeoNames pins used by workflow 4
  tools/                    One-time maintenance tools (3M/X3ML migration)
  tests/                    Unit tests
```

## Authentication options

For private Google Sheets, the script supports:

- OAuth access token;
- service account JSON key;
- environment variable GOOGLE_ACCESS_TOKEN.

For public Google Sheets, no authentication argument is required.

## Workflow 1: Spreadsheet export

Run from the `script/` directory (`uv` finds the project environment in the parent folder). Use `uv run python download_drive_excel.py --help` for all options.

Download a Google Sheet by share URL or file id:

```bash
uv run python download_drive_excel.py --url <GOOGLE_SHEETS_SHARE_URL>
uv run python download_drive_excel.py --file-id <GOOGLE_DRIVE_FILE_ID>
```

Process a downloaded `.xlsx` workbook without Google credentials or a network request:

```bash
uv run python download_drive_excel.py --file /path/to/US_Digitale_Rilevamento.xlsx --sheet-name US_data_SAS1 --output-dir /path/to/output --base-name Schede-Catalogo --stylesheet-map xslt/schede_us.xsl
```

Worksheet exports, including the sample XML and sample relations XML, are written under `<output-dir>/<base-name>/`. Omit `--sheet-name` to export every worksheet in the workbook.

### Stylesheet selection

For the US workbook, pass its stylesheet directly:

```bash
uv run python download_drive_excel.py --url <US_GOOGLE_SHEETS_SHARE_URL> --stylesheet-map xslt/schede_us.xsl
```

For automatic stylesheet selection by Google Drive file ID, save a JSON mapping such as `script/stylesheet-map.json`:

```json
{
	"CATALOG_FILE_ID": "xslt/default.xsl",
	"US_FILE_ID": "xslt/schede_us.xsl"
}
```

Paths in the JSON file are relative to the mapping file. The US stylesheet requires a `Unique_ID` column and resolves relation references against `US_ID`. Main XML fields follow the workbook column order; `Tipologia`, `excavation-event`, and `periodizzazione` group their corresponding fields at the position of the first source column in each group. Main and relation XML keep bare `Unique_ID` and `US_ID` values; relation references also use bare IDs. It removes trailing `.0` from integer-valued fields such as `Anno`, groups the category flags under `Tipologia`, splits the four multi-value fields, and processes relation columns by header name. Relation XML includes each source row and relation column; values in a relation column are emitted as nested `<value>` elements, split on commas, semicolons, or line breaks. Repeated relation headers are processed independently, and relation references are retained even if their target row is not in the workbook. Empty relation fields in the sample relations XML receive a `<value>0000</value>` placeholder; the full relations XML leaves them empty. Empty fields in the main XML and CSV exports are populated with `TEST`; the four dating fields are grouped under `periodizzazione`. Without `--stylesheet-map`, the script uses [script/xslt/default.xsl](script/xslt/default.xsl).

The stylesheet input is raw source XML. A custom stylesheet accepts `output_mode` values `csv`, `main`, and `relations` to produce the corresponding exports. Relation XML uses `*_Project_ID` elements and target `Project_ID` values for catalog relations, and `*_US_ID` elements and target `US_ID` values for US relations. Empty relation identifiers remain empty. Install `lxml` with the other dependencies to enable XSLT processing.

## Workflow 2: Entity extraction (optional)

Extract free-text entities with the separate [entity-extraction project](https://github.com/matteoLorenzini/entity-extraction), then pass its JSON output to this project. Use the same workbook and headers for both steps:

```bash
# In entity-extraction:
python extract_entities.py --file /path/to/Person.xlsx --fields Biography Role Contribution

# In source-data-transformer/script:
uv run python download_drive_excel.py --file /path/to/Person.xlsx --stylesheet-map xslt/person.xsl \
  --entities /path/to/entity-extraction/output_data/Person_entities.json
```

Existing extraction caches remain usable: pass their path to `--output` in the extraction project. See its README for installation, options, the JSON contract, and timeline XML. The timeline is mapped in [Workflow 3](#workflow-3-xml-to-cidoc-crm-rdf) with `e21_timeline.yaml`.
- With `--entities`, `<name>.xml` keeps only the spreadsheet fields and the entities are written to `<name>_entities.xml`, grouped by spreadsheet row: each `<row index="...">` holds the row's `<Unique_ID>` followed by `<Persons>` (other people mentioned), `<Places>`, `<Organizations>`, `<Roles>`, `<Events>`, and `<Works>`; empty groups are skipped. Each `<Person>`, `<Place>`, `<Organization>` and `<Work>` has a `<Relation>` (for example `teacher`, `place of study`, `employer`, or `author`) when the text states how it relates to the row's subject. Records have an `id` such as `place-sperlonga` (the same place gets the same id in every row) or `role-3` (numbered across the file). Places and organizations appear once per row with all their `<Source>` mentions (the verbatim sentence, its `row`, and its `field`) and list the roles and events that refer to them (`<Role ref="role-4">` with its `<Title>`, `<From>`, and `<To>`). Roles and events have a `<Title>` or `<Label>`, optional `<From>` / `<To>`, and `<Organization ref="..."/>` / `<Place ref="..."/>` references; events also have a `<Person ref="..."/>` for each other person involved, and those persons list the event back (`<Event ref="event-1">`). Identical roles found in several columns of a row are merged into one record with several sources. This is the input for the later RDF step. The CSV export is unchanged.

## Workflow 3: XML to CIDOC-CRM RDF

The XML to CIDOC-CRM step runs in Python (`rdflib`) from YAML mapping files, replacing the 3M/X3ML tool and its generator policy. A mapping file bundles the namespaces, the URI generators (the former generator policy), and the rules (the former X3ML). The mappings migrated from 3M are in `script/mappings/`: `e18.yaml` (catalog objects), `e21.yaml` (persons), `e53.yaml` (places and sites), `a8_a2.yaml` (stratigraphic units), and the `*_relations.yaml` files for the relation exports. The key `source` (`main`, `relations`, or `entities`) selects which export a mapping reads. The header of `script/transformer/rdf_mapper.py` documents the format.

Run a mapping as a pipeline step; the RDF is written next to the XML as `<export>_<mapping>.ttl`:

```powershell
cd script
uv run python download_drive_excel.py --file ..\Person.xlsx --stylesheet-map xslt\person.xsl --rdf-mapping mappings\e21.yaml
```

`--rdf-mapping` can be repeated, and `--rdf-format` selects `turtle` (default), `xml` (also `rdf` or `rdfxml`: nested RDF/XML with typed nodes and all mapping namespaces declared, written as `.rdf`, like the 3M output), `nt`, `nquads`, or `trig`. To transform an existing XML file on its own:

```powershell
uv run python xml_to_rdf.py --mapping mappings\e53.yaml --xml places_and_sites.xml --out places.ttl
```

- URIs follow the generator patterns; arguments are trimmed and percent-encoded (a space becomes `%20`, `/` is kept). `uuid` generators give deterministic `urn:uuid:` URIs (derived from the source file name and node position), so re-running gives the same URIs. `uri_or_uuid` keeps an absolute URI as is and otherwise derives a `urn:uuid:` from the text.
- Labels: `label` writes `rdfs:label` (3M `Literal` label generator) and `pref_label` writes `skos:prefLabel` (3M `prefLabel`).
- An entity (and the link that needs it) is skipped when one of its generator arguments is empty.
- `tools/x3ml_to_yaml.py <mapping.x3ml> <generator-policy.xml> <out.yaml> [--source relations]` migrates further 3M mappings. Review the result: the engine rejects unknown generators and namespace prefixes when loading.
- Tests: `cd script; uv run python -m unittest discover -s tests` checks the engine (conditions, intermediate entities, deterministic UUIDs, validation) and that every mapping in `script/mappings/` loads.

## Workflow 4: Places

Places are built in two steps. First map the places and sites XML to CIDOC-CRM with `e53.yaml`, then add the places from the source XML that the RDF does not yet contain. For each missing place, `add_missing_places.py` adds English and Italian appellations (translated with `Helsinki-NLP/opus-mt-en-it`) and coordinates from a local GeoNames dump, written as `POINT(lon lat)`.

1. Map the places and sites to RDF/XML (the same format as the 3M output):

```bash
cd script
uv run python xml_to_rdf.py --mapping mappings/e53.yaml --xml /path/to/places_and_sites.xml \
  --format xml --out /path/to/E53_new.rdf
```

2. Download the GeoNames dump once and keep it outside the repository. `allCountries.zip` is about 400 MB and unzips to a 1.8 GB `allCountries.txt`:

```bash
mkdir -p ~/.cache/geonames && cd ~/.cache/geonames
curl -O https://download.geonames.org/export/dump/allCountries.zip
unzip allCountries.zip
```

3. Make sure the translation dependencies are installed. `transformers`, `torch` and `sentencepiece` are declared in `pyproject.toml`, so `uv sync` (see Dependencies) installs them. The first run downloads the translation model (cached in `~/.cache/huggingface`).

4. Add the missing places, from the `script` directory:

```bash
uv run python add_missing_places.py \
  --rdf /path/to/E53_new.rdf \
  --places /path/to/places.xml \
  --geonames ~/.cache/geonames/allCountries.txt \
  --reconcile config/place_reconciliation.yaml \
  --out /path/to/E53_new_with_places.rdf
```

The input RDF is not modified; the result is written to `--out`. Add `-v` for detailed logging.

- To normalize a timeline RDF/XML generated by `e21_timeline.yaml` in the same run, also pass `--timeline /path/to/timeline.rdf --timeline-out /path/to/timeline_normalized.rdf`. Both options are required together. Timeline place IRIs based on source place IDs are replaced with the corresponding resolved place or site IRIs, including newly numbered places. Other timeline data and the input file are preserved. Timeline places absent from the source places are left unchanged and logged as warnings. Repeat this step after regenerating the timeline RDF.
- `--reconcile` points to [script/config/place_reconciliation.yaml](script/config/place_reconciliation.yaml). Its `reconcile:` section maps a source place id to an existing entity URI, so that place adds its missing names to that entity instead of creating a new one (for example, `tiberius-s-villa-in-sperlonga` → `site/1`). Places that are not listed are also matched by their English or Italian label against existing labels.
- Its `geonames:` section pins a source place to a GeoNames id when the name is ambiguous (for example, `italy` → `3175395` and `marburg` → `2873759`). Add an entry there when a place resolves to the wrong location.
- The script is idempotent: running it again on its own output adds nothing new.
- `--translation-model` selects another Hugging Face translation model.

Tests for this step: `cd script; uv run python -m unittest discover -s tests`.

## Code layout

`script/download_drive_excel.py` is a thin entry point. The implementation is in `script/transformer/`: `google_drive.py` (downloads and authentication), `source_xml.py` (worksheet to source XML), `xslt_runner.py` (stylesheet loading and exports), `entities.py` (entity JSON integration), `entity_tables.py` (per-domain entity files), `rdf_mapper.py` (XML to RDF mapping engine), and `cli.py` (argument parsing and orchestration). `script/xml_to_rdf.py` and `script/add_missing_places.py` are thin entry points for workflows 3 and 4.

## Tests

From the `script/` directory:

```bash
uv run python -m unittest discover -s tests
```

## Dependencies

The project is managed with [uv](https://docs.astral.sh/uv/) and Python 3.12 (see `.python-version`). From the repository root, create the environment and install the locked dependencies from `pyproject.toml` and `uv.lock`:

```bash
uv sync
```

Run scripts with `uv run` so they use this environment, for example `uv run python script/download_drive_excel.py --help`.

Entity extraction has separate dependencies; see the [entity-extraction project](https://github.com/matteoLorenzini/entity-extraction).