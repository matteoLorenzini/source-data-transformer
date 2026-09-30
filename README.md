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

Paths in the JSON file are relative to the mapping file. The US stylesheet requires a `Unique_ID` column and resolves relation references against `US_ID`. Main XML keeps the bare `Unique_ID` value; relation XML uses `http://www.lynx.com/resource/stratigraphic-unit/<id>` URIs. It removes trailing `.0` from integer-valued fields such as `Anno`, groups the category flags under `Tipologia`, splits the four multi-value fields, and processes relation columns by header name. Without `--stylesheet-map`, the script uses [script/xslt/default.xsl](script/xslt/default.xsl).

The stylesheet input is raw source XML. A custom stylesheet accepts `output_mode` values `csv`, `main`, and `relations` to produce the corresponding exports. Install `lxml` with the other dependencies to enable XSLT processing.

## Dependencies

Install required packages from requirements.txt:

```bash
pip install -r requirements.txt
```
