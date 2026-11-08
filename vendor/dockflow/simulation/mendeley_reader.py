"""Streaming reader for one Mendeley Chapter 5 cross-dock Excel instance.

Uses only Python's standard library. Does not load hundreds of thousands
of workbook rows into pandas and does not modify the source Excel.
"""
from __future__ import annotations

import hashlib
import posixpath
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

REQUIRED = {
    "inboundTrucks": ("Instance ID", "Truck ID", "Truck arrival time (min)"),
    "outboundTrucks": ("Instance ID", "Truck ID", "Arrival time (min)",
                       "Due date (min)", "Destination"),
    "pallets": ("Instance ID", "Pallet ID", "Due date (min)",
                "Destination", "Type", "TruckId"),
}


class DatasetFormatError(ValueError):
    """Invalid or inconsistent research input."""


def workbook_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sheet_paths(book: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    links = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in links}
    names = {}
    for sh in workbook.findall(f".//{{{MAIN}}}sheet"):
        name = sh.attrib["name"]
        target = targets[sh.attrib[f"{{{REL}}}id"]]
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join("xl", target))
        if resolved not in book.namelist():
            raise DatasetFormatError(f"Worksheet is missing: {resolved}")
        names[name] = resolved
    missing = set(REQUIRED) - names.keys()
    if missing:
        raise DatasetFormatError(f"Missing worksheets: {sorted(missing)}")
    return names


def _strings(book: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{MAIN}}}t"))
        for item in root.findall(f"{{{MAIN}}}si")
    ]


def _cell_value(cell: ET.Element, strings: list[str]) -> str | None:
    value = cell.find(f"{{{MAIN}}}v")
    if value is None:
        if cell.attrib.get("t") == "inlineStr":
            inline = cell.find(f"{{{MAIN}}}is")
            return "".join(x.text or "" for x in inline.iter(f"{{{MAIN}}}t")) if inline is not None else None
        return None
    if cell.attrib.get("t") == "s":
        return strings[int(value.text)]
    return value.text


def _read_sheet(
    book: ZipFile, member: str, strings: list[str], required: tuple[str, ...],
    instance_id: int,
) -> list[dict[str, str]]:
    header = None
    records = []
    found = False
    with book.open(member) as source:
        context = ET.iterparse(source, events=("start", "end"))
        _, root = next(context)
        for action, row in context:
            if action != "end" or row.tag != f"{{{MAIN}}}row":
                continue
            cols = {
                "".join(c for c in cell.attrib.get("r", "") if c.isalpha()): _cell_value(cell, strings)
                for cell in row.findall(f"{{{MAIN}}}c")
            }
            cells = list(cols.values())
            if header is None:
                header = tuple((x or "").strip() for x in cells)
                if len(set(header)) != len(header) or not set(required) <= set(header):
                    raise DatasetFormatError(f"Invalid columns in {member}: {header}")
                root.clear()
                continue
            if not cells or cells[0] is None:
                root.clear()
                continue
            try:
                current_instance = int(float(cells[0]))
            except (ValueError, TypeError) as exc:
                raise DatasetFormatError(f"Invalid instance ID in {member}") from exc
            if current_instance != instance_id:
                if found:
                    root.clear()
                    break  # Original workbook is grouped by Instance ID.
                root.clear()
                continue
            found = True
            record = dict(zip(header, cells))
            records.append({k: record[k] for k in required})
            root.clear()
    if not records:
        raise DatasetFormatError(f"Instance {instance_id} is absent in {member}")
    return records


def read_instance(path: str | Path, instance_id: int) -> dict[str, list[dict[str, str]]]:
    """Read a single complete instance from the three workbook worksheets."""
    if not isinstance(instance_id, int) or isinstance(instance_id, bool) or instance_id < 1:
        raise ValueError("instance_id must be a positive integer")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with ZipFile(path) as book:
        mapping = _sheet_paths(book)
        strings = _strings(book)
        return {
            key: _read_sheet(book, mapping[key], strings, columns, instance_id)
            for key, columns in REQUIRED.items()
        }
