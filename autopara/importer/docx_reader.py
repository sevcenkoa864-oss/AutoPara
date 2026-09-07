"""Physical layer of the .docx import: zip -> XML -> a cell grid with merge metadata.

A .docx is a zip archive. We read ``word/document.xml`` for the content and
``word/_rels/document.xml.rels`` to resolve hyperlink relationship ids into real URLs.

This module deliberately avoids any higher-level docx library. The schedule's meaning is carried by
real cell merges (``w:gridSpan``, ``w:vMerge``) and by hyperlink relationships; converters that
flatten tables to text or HTML either duplicate merged cells or drop the link targets entirely.
See docs/BACKEND.md rules R1, R3, R4, R5.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

DOCUMENT_PART = "word/document.xml"
RELS_PART = "word/_rels/document.xml.rels"


@dataclass
class Cell:
    """One ``<w:tc>``, positioned by logical column rather than by index.

    ``column`` is the running sum of the ``gridSpan`` of preceding cells in the row, so it stays
    correct even though merged rows contain fewer ``<w:tc>`` elements than the table has columns
    (BACKEND.md R1).
    """

    column: int
    span: int = 1
    vmerge: str | None = None  # None | "restart" | "continue"
    lines: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    @property
    def last_column(self) -> int:
        return self.column + self.span - 1

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def overlaps(self, lo: int, hi: int) -> bool:
        """True when this cell's column range intersects ``[lo, hi]`` (BACKEND.md R2)."""
        return not (self.last_column < lo or self.column > hi)

    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)

    def at(self, column: int) -> Cell | None:
        """The cell covering ``column``, or None if the row does not reach it."""
        for cell in self.cells:
            if cell.column <= column <= cell.last_column:
                return cell
        return None


@dataclass
class Table:
    grid_columns: int
    rows: list[Row] = field(default_factory=list)


@dataclass
class Document:
    """Top-level body content in document order, so headings can be paired with tables."""

    blocks: list[tuple[str, object]] = field(default_factory=list)  # ("p", str) | ("tbl", Table)

    @property
    def tables(self) -> list[Table]:
        return [b for kind, b in self.blocks if kind == "tbl"]

    def paragraphs(self) -> list[str]:
        return [b for kind, b in self.blocks if kind == "p"]


def _read_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map relationship id -> target URL for external hyperlinks (BACKEND.md R3)."""
    try:
        raw = archive.read(RELS_PART)
    except KeyError:
        return {}
    root = ET.fromstring(raw)
    rels: dict[str, str] = {}
    for rel in root:
        rid = rel.get("Id")
        target = rel.get("Target")
        if rid and target and "hyperlink" in (rel.get("Type") or ""):
            rels[rid] = target
    return rels


def _paragraph_segments(paragraph: ET.Element, rels: dict[str, str]) -> tuple[list[str], list[str]]:
    """Split one ``<w:p>`` into display lines and hyperlink targets.

    ``<w:br/>`` inside a paragraph is a line break, and the schedule uses it to stack
    subject / teacher / URL inside a single cell (BACKEND.md R9).
    """
    buffer: list[str] = []
    links: list[str] = []
    for node in paragraph.iter():
        if node.tag == W + "t":
            buffer.append(node.text or "")
        elif node.tag in (W + "br", W + "cr"):
            buffer.append("\n")
        elif node.tag == W + "tab":
            buffer.append(" ")
        elif node.tag == W + "hyperlink":
            rid = node.get(R + "id")
            if rid and rid in rels:
                links.append(rels[rid])
    lines = [part.strip() for part in "".join(buffer).split("\n")]
    return [line for line in lines if line], links


def _parse_cell(tc: ET.Element, column: int, rels: dict[str, str]) -> Cell:
    span = 1
    vmerge: str | None = None
    props = tc.find(W + "tcPr")
    if props is not None:
        grid_span = props.find(W + "gridSpan")
        if grid_span is not None:
            try:
                span = max(1, int(grid_span.get(W + "val") or 1))
            except ValueError:
                span = 1
        merge = props.find(W + "vMerge")
        if merge is not None:
            # An omitted w:val means "continue" per the OOXML spec.
            vmerge = merge.get(W + "val") or "continue"

    lines: list[str] = []
    links: list[str] = []
    for paragraph in tc.findall(W + "p"):
        para_lines, para_links = _paragraph_segments(paragraph, rels)
        lines.extend(para_lines)
        links.extend(para_links)
    return Cell(column=column, span=span, vmerge=vmerge, lines=lines, links=links)


def _parse_row(tr: ET.Element, rels: dict[str, str]) -> Row:
    row = Row()
    column = 0
    for tc in tr.findall(W + "tc"):
        cell = _parse_cell(tc, column, rels)
        row.cells.append(cell)
        column += cell.span
    return row


def _parse_table(tbl: ET.Element, rels: dict[str, str]) -> Table:
    grid = tbl.find(W + "tblGrid")
    grid_columns = len(grid.findall(W + "gridCol")) if grid is not None else 0
    table = Table(grid_columns=grid_columns)
    for tr in tbl.findall(W + "tr"):
        table.rows.append(_parse_row(tr, rels))
    return table


def read_document(path: str) -> Document:
    """Read a .docx into a Document of paragraphs and tables, in document order."""
    with zipfile.ZipFile(path) as archive:
        rels = _read_relationships(archive)
        root = ET.fromstring(archive.read(DOCUMENT_PART))

    body = root.find(W + "body")
    document = Document()
    if body is None:
        return document

    for child in body:
        if child.tag == W + "p":
            lines, _ = _paragraph_segments(child, rels)
            text = " ".join(lines).strip()
            if text:
                document.blocks.append(("p", text))
        elif child.tag == W + "tbl":
            document.blocks.append(("tbl", _parse_table(child, rels)))
    return document
