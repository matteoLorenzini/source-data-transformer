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

Show all options:

```bash
python download_drive_excel.py --help
```

## Dependencies

Install required packages from requirements.txt:

```bash
pip install -r requirements.txt
```
