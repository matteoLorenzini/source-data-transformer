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

## Entity extraction (CIDOC-CRM)

Free-text columns, such as the `Biography`, `Role`, and `Contribution` columns of `Person.xlsx`, can be turned into typed entities (person, place, organization, date, role, work, event), each stored with the verbatim sentence it came from. This is a two-step process so the extracted data can be reviewed and cached:

```powershell
cd script
ollama pull qwen2.5:7b
python extract_entities.py --file ..\Person.xlsx --fields Biography Role Contribution
python download_drive_excel.py --file ..\Person.xlsx --stylesheet-map xslt\person.xsl --entities output_data\Person_entities.json
```

- `extract_entities.py` writes `output_data/<workbook>_entities.json`. Results are cached per cell text, so re-runs only call the model for new or changed cells. Use `--dry-run` to list the cells that would be sent, `--refresh` to re-extract, and `--base-url` / `--model` (or `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`) to use another OpenAI-compatible endpoint. By default it uses a free local [Ollama](https://ollama.com) server and needs no account or API key; set `OLLAMA_CONTEXT_LENGTH=8192` before starting Ollama so long biographies are not truncated. On a machine without a GPU, a smaller model (for example `--model qwen2.5:3b`) is faster. Entities whose context is not found verbatim in the source text are discarded.
- `person.xsl` renders the entities in a `<CRM_Entities>` block after the original fields, using CIDOC-CRM classes: `E21_Person`, `E53_Place`, `E74_Group`, `E52_Time-Span`, `E73_Information_Object`, `E7_Activity` (roles), and `E5_Event`. Each carries its `source_field` and a `P3_has_note` with the context. The CSV export is unchanged.

## Code layout

`script/download_drive_excel.py` is a thin entry point. The implementation is in `script/transformer/`: `google_drive.py` (downloads and authentication), `source_xml.py` (worksheet to source XML), `xslt_runner.py` (stylesheet loading and exports), `entities.py` and `llm_extractor.py` (entity extraction), and `cli.py` (argument parsing and orchestration).

## Dependencies

Install required packages from requirements.txt:

```bash
pip install -r requirements.txt
```
