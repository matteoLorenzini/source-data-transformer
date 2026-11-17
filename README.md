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

## Main tasks

The script implements the following tasks:

1. Download spreadsheet data from Google Sheets.
2. Export worksheet content to CSV.
3. Export worksheet content to XML.
4. Preserve row and column structure for downstream transformation and mapping.
5. Normalize selected multi-value fields into repeated XML sub-elements.

## Input and output

- Input source: Google Sheets documents (public or authenticated access).
- Output formats: CSV and XML.
- Default output directory: script/output_data.

## Authentication options

For private Google Sheets, the script supports:

- OAuth access token;
- service account JSON key;
- environment variable GOOGLE_ACCESS_TOKEN.

For public Google Sheets, no authentication argument is required.

## Usage

From the repository root, both commands are supported:

```bash
python download_drive_excel.py --url <GOOGLE_SHEETS_SHARE_URL>
python script/download_drive_excel.py --url <GOOGLE_SHEETS_SHARE_URL>
```

You can also pass a file id directly:

```bash
python download_drive_excel.py --file-id <GOOGLE_DRIVE_FILE_ID>
```

From the `script` directory, process a downloaded `.xlsx` workbook without Google credentials or a network request:

```bash
python .\download_drive_excel.py --file ..\US_Digitale_Rilevamento.xlsx --sheet-name US_data_SAS1 --output-dir ..\..\lynx_dataset\raw_data\SPE\ --base-name Schede-Catalogo --stylesheet-map .\xslt\schede_us.xsl
```

Worksheet exports, including the sample XML and sample relations XML, are written under `<output-dir>/<base-name>/`. For example, with the command above, they are written to `..\..\lynx_dataset\raw_data\SPE\Schede-Catalogo\`.

Omit `--sheet-name` to export every worksheet in the workbook.

Show all options:

```bash
python download_drive_excel.py --help
```

## XSLT transformations

For this US workbook, pass its stylesheet directly. From the repository root:

```bash
python script/download_drive_excel.py --url <US_GOOGLE_SHEETS_SHARE_URL> --stylesheet-map script/xslt/schede_us.xsl
```

When running the script from the `script` directory, use paths relative to that directory:

```bash
python .\download_drive_excel.py --url <US_GOOGLE_SHEETS_SHARE_URL> --output-dir ..\..\lynx_dataset\raw_data\SPE\ --base-name Schede-Catalogo --stylesheet-map .\xslt\schede_us.xsl
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

## Entity extraction

Free-text columns, such as the `Biography`, `Role`, and `Contribution` columns of `Person.xlsx`, can be turned into typed entities (person, place, organization, role, work, event), each stored with the verbatim sentence it came from. Dates are not entities of their own; they are the `date` or `from` / `to` of a role, event, or work. This is a two-step process so the extracted data can be reviewed and cached:

```powershell
cd script
python extract_entities.py --file ..\Person.xlsx --fields Biography Role Contribution
python download_drive_excel.py --file ..\Person.xlsx --stylesheet-map xslt\person.xsl --entities output_data\Person_entities.json
```

On Linux, use `/` for the file paths:

```bash
cd script
python extract_entities.py --file ../Person.xlsx --fields Biography Role Contribution
python download_drive_excel.py --file ../Person.xlsx --stylesheet-map xslt/person.xsl --entities output_data/Person_entities.json
```

### Extraction model

`extract_entities.py` uses a local [GLiNER](https://github.com/urchade/GLiNER) model (`transformer/gliner_extractor.py`). It finds people, places, organizations, job titles, and publications sentence by sentence; roles are then paired with their dates and institution by their position in the sentence (`professor at Bochum (1965-1977) and Marburg (from 1978)` gives two roles). It runs on CPU in seconds per cell and needs no server, account, or API key. Install it once in the virtual environment; on a machine without a GPU, install the CPU build of PyTorch first:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install gliner sentencepiece protobuf
```

The model (`--gliner-model`, default `urchade/gliner_multi-v2.1`, multilingual) is downloaded from Hugging Face on the first run and cached in `~/.cache/huggingface`. `--threshold` (default `0.4`) sets the confidence: lower finds more spans, higher fewer. The labels sent to the model are in `LABELS` at the top of `gliner_extractor.py`.

On top of GLiNER, `gliner_extractor.py` cleans the spans: pronouns and possessives (`Tiberius` in `Tiberius's Villa`) are not persons, places are extended or trimmed (`Tiberius's Villa in Sperlonga`, `Baiae` instead of `Baiae excavations`), common job titles GLiNER misses are added (`TITLE_RE`), quoted titles are works as a whole, and sentences are not split at abbreviations (`vs.`, `trans.`) or inside URLs. The words before a person give its role in the event (`RELATION_CUES`): `under X` gives `teacher`, `his mentors X, Y, and Z` gives `mentor` for every name of the list.

Cells extracted with another model, including those from the former Ollama backend, are extracted again automatically; there is no need for `--refresh` when switching.

### Events

Events (graduation, habilitation, doctorate, birth, death, excavation, survey, expedition, exhibition, conference, award, marriage) are found by rules in the cell text; these carry `"detected_by": "rule"`. The cue words are in `EVENT_CUES` in `extract_entities.py`. Each event is then completed from its own sentence and the other entities of the same cell:

- `date` for a single year (`1956`), or `from` / `to` for a span (`In the 1970s and 1980s` gives `1970s` / `1980s`);
- `place` (`graduated from Marburg`), `organization` (`the Rome Soprintendenza's excavations`), and `participants` (`under Friedrich Matz`, with the role `teacher`).

A place, organization, or participant that is neither an entity extracted from the same cell nor a proper name in the sentence is dropped and filled again from the text, so values such as `Hadrian's Villa and the Baiae` do not reach the output. Values already present are never overwritten. These steps also run on cached cells, so a re-run fixes earlier results without extracting again.

### Options and outputs

- `extract_entities.py` writes `output_data/<workbook>_entities.json` (or `--output`). Results are cached per cell text, so re-runs only extract new or changed cells. Each cached cell records its `subject` (the `--subject-field` column, default `Name_Surname`) and its `extractor`. Use `--dry-run` to list the cells that would be extracted without loading the model, `--refresh` to extract every cell again, and `--prune` to remove cached cells whose text is no longer in the workbook (for example old versions of an edited cell; not combinable with `--sheet-name`; preview with `--dry-run --prune`). Entities whose context is not found verbatim in the source text are discarded.
- It also writes `<workbook>_entities_records.xml` next to the JSON (or `--xml-output <path>`; `--no-xml` to skip), covering the rows processed in that run. The entities of each subject are merged across columns (the same role in `Biography` and `Role`, or the same event described in two columns, becomes one record; `from 1978` and `1978-1985` merge into `1978-1985`) and written as one `<record>` per subject:

  ```xml
  <record id="bernard-andreae">
    <subject id="bernard-andreae"><name>Bernard Andreae</name></subject>
    <event id="7f6993f923b2" source_field="BIOGRAPHY" detected_by="rule">
      <type id="graduation">Graduation</type>
      <label>Graduation at Marburg – Bernard Andreae</label>
      <timespan id="7f6993f923b2-ts">
        <label>1956</label><begin>1956-01-01T00:00:00</begin><end>1956-12-31T23:59:59</end>
      </timespan>
      <place id="marburg">Marburg</place>
      <participants>
        <participant id="friedrich-matz"><name>Friedrich Matz</name><role id="teacher">Teacher</role></participant>
      </participants>
      <note>Bernard Andreae graduated from Marburg in 1956 under Friedrich Matz, …</note>
    </event>
    <role id="…"> … </role>
  </record>
  ```

  `<event>` (the subject took part), `<role>` (the subject carried it out), `<birth>`, `<death>`, `<work>` (with `<title>` and `<creation>`), and `<occupation>` (a role without date, place, or organization) each have a `<type>`, `<label>`, `<timespan>` (`<begin>` / `<end>` as `xsd:dateTime`; a decade covers its ten years; an open span such as `from 1978` has no `<end>`), `<place>`, `<organization>`, `<participants>` (each `<participant>` with its `<name>` and, when the text states it, its `<role>` in the event, such as `Teacher` or `Mentor`), and `<note>` (the source sentence) where known. Every element that becomes a CIDOC-CRM entity has a stable `id`: a slug for people, places, organizations, and types (the same place gets the same id in every record), and a hash for events and roles. The intended classes are listed at the top of `extract_entities.py` (E21_Person, E7_Activity, E67_Birth, E69_Death, E52_Time-Span, E53_Place, E74_Group, E55_Type, E73_Information_Object / E65_Creation).
- With `--entities`, `<name>.xml` keeps only the spreadsheet fields and the entities are written to `<name>_entities.xml`, grouped by spreadsheet row: each `<row index="...">` holds the row's `<Unique_ID>` followed by `<Persons>` (other people mentioned), `<Places>`, `<Organizations>`, `<Roles>`, `<Events>`, and `<Works>`; empty groups are skipped. Each `<Person>`, `<Place>`, `<Organization>` and `<Work>` has a `<Relation>` (for example `teacher`, `place of study`, `employer`, or `author`) when the text states how it relates to the row's subject. Records have an `id` such as `place-sperlonga` (the same place gets the same id in every row) or `role-3` (numbered across the file). Places and organizations appear once per row with all their `<Source>` mentions (the verbatim sentence, its `row`, and its `field`) and list the roles and events that refer to them (`<Role ref="role-4">` with its `<Title>`, `<From>`, and `<To>`). Roles and events have a `<Title>` or `<Label>`, optional `<From>` / `<To>`, and `<Organization ref="..."/>` / `<Place ref="..."/>` references; events also have a `<Person ref="..."/>` for each other person involved, and those persons list the event back (`<Event ref="event-1">`). Identical roles found in several columns of a row are merged into one record with several sources. This is the input for the later RDF step. The CSV export is unchanged.

## RDF (CIDOC-CRM) mapping

The XML to CIDOC-CRM step runs in Python (`rdflib`) from YAML mapping files, replacing the 3M/X3ML tool and its generator policy. A mapping file bundles the namespaces, the URI generators (the former generator policy), and the rules (the former X3ML). The mappings migrated from 3M are in `script/mappings/`: `e18.yaml` (catalog objects), `e21.yaml` (persons), `e53.yaml` (places and sites), `a8_a2.yaml` (stratigraphic units), and the `*_relations.yaml` files for the relation exports. The key `source` (`main`, `relations`, or `entities`) selects which export a mapping reads. The header of `script/transformer/rdf_mapper.py` documents the format.

Run a mapping as a pipeline step; the RDF is written next to the XML as `<export>_<mapping>.ttl`:

```powershell
cd script
python download_drive_excel.py --file ..\Person.xlsx --stylesheet-map xslt\person.xsl --rdf-mapping mappings\e21.yaml
```

`--rdf-mapping` can be repeated, and `--rdf-format` selects `turtle` (default), `xml` (also `rdf` or `rdfxml`: nested RDF/XML with typed nodes and all mapping namespaces declared, written as `.rdf`, like the 3M output), `nt`, `nquads`, or `trig`. To transform an existing XML file on its own:

```powershell
python xml_to_rdf.py --mapping mappings\e53.yaml --xml places_and_sites.xml --out places.ttl
```

- URIs follow the generator patterns; arguments are trimmed and percent-encoded (a space becomes `%20`, `/` is kept). `uuid` generators give deterministic `urn:uuid:` URIs (derived from the source file name and node position), so re-running gives the same URIs. `uri_or_uuid` keeps an absolute URI as is and otherwise derives a `urn:uuid:` from the text.
- Labels: `label` writes `rdfs:label` (3M `Literal` label generator) and `pref_label` writes `skos:prefLabel` (3M `prefLabel`).
- An entity (and the link that needs it) is skipped when one of its generator arguments is empty.
- `script/x3ml_to_yaml.py <mapping.x3ml> <generator-policy.xml> <out.yaml> [--source relations]` migrates further 3M mappings. Review the result: the engine rejects unknown generators and namespace prefixes when loading.
- Tests: `cd script; python -m unittest discover -s tests` checks the engine (conditions, intermediate entities, deterministic UUIDs, validation) and that every mapping in `script/mappings/` loads.

## Code layout

`script/download_drive_excel.py` is a thin entry point. The implementation is in `script/transformer/`: `google_drive.py` (downloads and authentication), `source_xml.py` (worksheet to source XML), `xslt_runner.py` (stylesheet loading and exports), `entities.py`, `gliner_extractor.py` (entity extraction; event rules, completion, and the records XML are in `script/extract_entities.py`), `entity_tables.py` (per-domain entity files), `rdf_mapper.py` (XML to RDF mapping engine), and `cli.py` (argument parsing and orchestration).

## Dependencies

Install required packages from requirements.txt:

```bash
pip install -r requirements.txt
```

Entity extraction also needs `gliner`, `sentencepiece`, and `protobuf` (see [Extraction model](#extraction-model)); without a GPU, install the CPU build of PyTorch before `gliner`.