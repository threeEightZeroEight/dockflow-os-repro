#!/usr/bin/env python3
"""将 report.md 转换为排版规范的 docx（pandoc + python-docx 后处理）。"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = Path(__file__).resolve().parent
MD = HERE / "report.md"
OUT = HERE / "report.docx"
PANDOC = shutil.which("pandoc") or "pandoc"


def convert() -> None:
    subprocess.run(
        [PANDOC, MD.name, "-o", OUT.name, "--resource-path=.",
         "--from=markdown+autolink_bare_uris"],
        cwd=HERE,
        check=True,
    )
    print(f"pandoc 转换完成：{OUT}")


def _set_style_font(style, latin: str, east: str, size: float | None = None) -> None:
    style.font.name = latin
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), east)
    if size is not None:
        style.font.size = Pt(size)


def _fix_table_layout(table) -> None:
    """pandoc 生成的表格常缺 tblGrid 且 tblW=0，Word 中会被压扁。"""
    tbl = table._tbl
    tbl_pr = tbl.tblPr

    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "pct")
    tbl_w.set(qn("w:w"), "5000")

    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "autofit")

    ncols = max((len(row.cells) for row in table.rows), default=0)
    if not ncols:
        return
    grid = tbl.find(qn("w:tblGrid"))
    existing = len(grid.findall(qn("w:gridCol"))) if grid is not None else 0
    if existing == ncols:
        return
    if grid is not None:
        tbl.remove(grid)
    grid = OxmlElement("w:tblGrid")
    width = int(8957 / ncols)
    for _ in range(ncols):
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    tbl_pr.addnext(grid)


def _table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "8A8A8A")
        borders.append(element)
    tbl_pr.append(borders)


def postprocess() -> None:
    doc = Document(str(OUT))

    normal = doc.styles["Normal"]
    _set_style_font(normal, "Times New Roman", "宋体", 10.5)
    normal.paragraph_format.line_spacing = 1.45
    normal.paragraph_format.space_after = Pt(4)

    for name, size in (("Title", 18), ("Heading 1", 15), ("Heading 2", 13),
                       ("Heading 3", 11.5), ("Heading 4", 11)):
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        _set_style_font(style, "Times New Roman", "黑体", size)
        style.font.bold = True
        style.paragraph_format.space_before = Pt(10)
        style.paragraph_format.space_after = Pt(6)

    for name in ("Source Code", "Verbatim Char"):
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        _set_style_font(style, "Consolas", "宋体", 9)

    for section in doc.sections:
        section.top_margin = Cm(2.4)
        section.bottom_margin = Cm(2.4)
        section.left_margin = Cm(2.6)
        section.right_margin = Cm(2.6)

    drawing_tag = qn("w:drawing")
    for paragraph in doc.paragraphs:
        if paragraph._element.findall(f".//{drawing_tag}"):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for table in doc.tables:
        _fix_table_layout(table)
        _table_borders(table)
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.space_after = Pt(1)
                    paragraph.paragraph_format.line_spacing = 1.15
                    for run in paragraph.runs:
                        run.font.size = Pt(9)

    # 页码（页脚居中）
    for section in doc.sections:
        footer = section.footer
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        field_begin = OxmlElement("w:fldChar")
        field_begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = "PAGE"
        field_end = OxmlElement("w:fldChar")
        field_end.set(qn("w:fldCharType"), "end")
        run._r.append(field_begin)
        run._r.append(instr)
        run._r.append(field_end)

    doc.save(str(OUT))
    print(f"后处理完成：{OUT}")


def report() -> None:
    doc = Document(str(OUT))
    with zipfile.ZipFile(OUT) as archive:
        media = [n for n in archive.namelist() if n.startswith("word/media/")]
    print("\n=== docx 自检 ===")
    print(f"文件大小：{OUT.stat().st_size / 1024:.1f} KB")
    print(f"段落数：{len(doc.paragraphs)}｜表格数：{len(doc.tables)}｜内嵌图片：{len(media)}")
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    print("标题数：", len(headings))
    for text in headings[:12]:
        print("  -", text[:60])


def main() -> None:
    convert()
    postprocess()
    report()


if __name__ == "__main__":
    main()