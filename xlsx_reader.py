from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def column_index(cell_ref: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_ref).group(1)
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def read_workbook(path: Path) -> dict[str, list[list[object]]]:
    with zipfile.ZipFile(path) as zf:
        shared_strings = _read_shared_strings(zf)
        sheet_targets = _sheet_targets(zf)
        return {
            name: _read_sheet(zf, target, shared_strings)
            for name, target in sheet_targets.items()
        }


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("a:si", NS):
        values.append("".join(t.text or "" for t in item.findall(".//a:t", NS)))
    return values


def _sheet_targets(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    sheets = {}
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        name = sheet.attrib["name"]
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rid_to_target[rid]
        if target.startswith("/xl/"):
            target = target[4:]
        elif not target.startswith("worksheets/"):
            target = "worksheets/" + target.split("/")[-1]
        sheets[name] = "xl/" + target
    return sheets


def _read_sheet(
    zf: zipfile.ZipFile,
    target: str,
    shared_strings: list[str],
) -> list[list[object]]:
    root = ET.fromstring(zf.read(target))
    parsed_rows = []
    max_width = 0

    for row in root.findall("a:sheetData/a:row", NS):
        values_by_col = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "A1")
            values_by_col[column_index(ref)] = _cell_value(cell, shared_strings)
        if values_by_col:
            max_width = max(max_width, max(values_by_col) + 1)
            parsed_rows.append(values_by_col)

    rows = []
    for values_by_col in parsed_rows:
        rows.append([values_by_col.get(index, "") for index in range(max_width)])
    return rows


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
    value = cell.find("a:v", NS)
    if value is None:
        return ""

    raw = value.text or ""
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        return shared_strings[int(raw)] if raw else ""
    if cell_type == "str":
        return raw

    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() else number
