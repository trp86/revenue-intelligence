"""Read one Excel sheet as text, keeping true Excel row numbers.

The Excel reader (fastexcel) starts its frame at the first cell that has a value, not at
row 1, so its row index is not the Excel row number. `read_sheet` finds that first row from
the sheet's XML and returns it with the frame: frame row `i` is Excel row `first_row + i`.
A formatted but empty cell does not count as a value; a whitespace-only text cell does.

Files under data/raw are only opened through `revint.ingest.raw.open_raw`.
"""

from __future__ import annotations

import html
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fastexcel
import polars as pl

from revint.ingest.raw import open_raw

_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_SHEET_RE = re.compile(r"<sheet\b[^>]*>")
_ATTR_RE = re.compile(r'([\w:]+)="([^"]*)"')
_DIMENSION_RE = re.compile(rb'<dimension ref="([^"]+)"')
_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")


@dataclass(frozen=True)
class SheetData:
    """All cells of one sheet as text. Frame row `i` is Excel row `first_row + i`."""

    name: str
    frame: pl.DataFrame
    first_row: int
    dimension: str

    @property
    def last_row(self) -> int:
        return self.first_row + self.frame.height - 1


def column_letter(number: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet_entries(workbook: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(sheet name, relationship id) in workbook order."""
    xml = workbook.read("xl/workbook.xml").decode("utf-8")
    entries = []
    for tag in _SHEET_RE.findall(xml):
        attrs = dict(_ATTR_RE.findall(tag))
        entries.append((html.unescape(attrs["name"]), attrs["r:id"]))
    return entries


def sheet_names(workbook: zipfile.ZipFile) -> list[str]:
    return [name for name, _ in _sheet_entries(workbook)]


def sheet_xml_path(workbook: zipfile.ZipFile, sheet: str) -> str:
    """Path of the sheet's XML inside the workbook archive."""
    entries = dict(_sheet_entries(workbook))
    if sheet not in entries:
        raise ValueError(f"no sheet named '{sheet}'; sheets: {', '.join(sheet_names(workbook))}")
    rels = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.get("Id") == entries[sheet]:
            target = rel.get("Target", "")
            return target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    raise ValueError(f"sheet '{sheet}' has no relationship entry")


def sheet_dimension(workbook: zipfile.ZipFile, xml_path: str) -> str:
    """The used range the sheet declares, for example `A4:BW662135`."""
    with workbook.open(xml_path) as stream:
        match = _DIMENSION_RE.search(stream.read(65536))
    if match is None:
        raise ValueError("sheet declares no dimension")
    return match.group(1).decode("ascii")


def first_value_row(workbook: zipfile.ZipFile, xml_path: str) -> int:
    """Excel row number of the first cell that holds a value (stops reading there)."""
    with workbook.open(xml_path) as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if not element.tag.endswith("}c") and element.tag != "c":
                continue
            has_value = any(
                (child.tag.endswith("}v") or child.tag == "v") and child.text
                or child.tag.endswith("}is")
                or child.tag == "is"
                for child in element
            )
            if has_value:
                match = _CELL_REF_RE.match(element.get("r", ""))
                if match is None:
                    raise ValueError("cell without a valid reference")
                return int(match.group(2))
            element.clear()
    raise ValueError("sheet has no cell with a value")


def read_sheet(data: bytes, sheet: str) -> SheetData:
    """Load every cell of `sheet` as text, aligned to Excel rows.

    Raises `ValueError` if the sheet is missing, empty, or does not start in column A.
    """
    workbook = zipfile.ZipFile(io.BytesIO(data))
    xml_path = sheet_xml_path(workbook, sheet)
    dimension = sheet_dimension(workbook, xml_path)
    first_column = _CELL_REF_RE.match(dimension.split(":")[0])
    if first_column is None or first_column.group(1) != "A":
        raise ValueError(f"sheet '{sheet}' does not start in column A (used range {dimension})")
    first_row = first_value_row(workbook, xml_path)
    loaded = fastexcel.read_excel(data).load_sheet(sheet, header_row=None, dtypes="string")
    return SheetData(
        name=sheet, frame=loaded.to_polars(), first_row=first_row, dimension=dimension
    )


def find_workbook(raw_dir: Path, sheet: str) -> Path:
    """The one .xlsx file under `raw_dir` that has a sheet named `sheet`.

    Files are opened read-only through `open_raw`; only the archive index is read.
    Raises `ValueError` if no file, or more than one, has the sheet.
    """
    matches: list[Path] = []
    for candidate in sorted(raw_dir.glob("*.xlsx"), key=lambda p: p.name):
        try:
            with open_raw(Path(candidate.name), raw_dir) as handle:
                names = sheet_names(zipfile.ZipFile(handle))
        except (zipfile.BadZipFile, KeyError):
            continue
        if sheet in names:
            matches.append(candidate)
    if not matches:
        raise ValueError(f"no workbook in the raw folder has a sheet named '{sheet}'")
    if len(matches) > 1:
        listed = ", ".join(p.name for p in matches)
        raise ValueError(f"more than one workbook has a sheet named '{sheet}': {listed}")
    return matches[0]
