from __future__ import annotations

from pathlib import Path
from urllib.request import urlretrieve


SHEET_ID = "1UCpEBXmOWNA57eLXH62WffnPrflly6OwmDm242JYhp8"
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
OUTPUT_PATH = Path(__file__).with_name("data") / "fuman-scorecard.xlsx"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(EXPORT_URL, OUTPUT_PATH)
    print(f"Downloaded latest Google Sheet to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
