"""Download Google Sheets and transform worksheet data with external XSLT.

Usage:
    download_drive_excel.py --file <LOCAL_XLSX_PATH>
    download_drive_excel.py --file-id <GOOGLE_DRIVE_FILE_ID>
    download_drive_excel.py --url <GOOGLE_SHEETS_SHARE_URL>
    download_drive_excel.py --url <GOOGLE_SHEETS_SHARE_URL> --stylesheet-map <JSON_MAP>

The script serializes raw worksheet data, then applies the default stylesheet
or one selected by spreadsheet file ID to produce CSV, XML, and relation XML.
The implementation lives in the transformer package.
"""

from transformer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
