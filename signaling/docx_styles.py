"""Helpers visuais pequenos para os relatórios Word de sinalização."""

from docx.document import Document as DocumentObject
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.table import _Cell, Table


NAVY = "003366"
SOFT_GRAY = "F4F6F8"
ZEBRA_GRAY = "F8F9FA"
LIGHT_BORDER = "D9D9D9"
WHITE = "FFFFFF"


def configure_document_styles(document: DocumentObject) -> None:
    section = document.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(1.7)
    section.right_margin = Cm(1.7)
    section.header_distance = Cm(0.7)
    section.footer_distance = Cm(0.7)

    normal = document.styles["Normal"]
    _set_style_font(normal, "Calibri", 10)
    normal.paragraph_format.space_after = Pt(5)

    title = document.styles["Title"]
    _set_style_font(title, "Arial", 18, color=NAVY, bold=True)
    title.paragraph_format.space_before = Pt(6)
    title.paragraph_format.space_after = Pt(12)
    title.paragraph_format.keep_with_next = True

    heading = document.styles["Heading 1"]
    _set_style_font(heading, "Arial", 13, color=NAVY, bold=True)
    heading.paragraph_format.space_before = Pt(12)
    heading.paragraph_format.space_after = Pt(6)
    heading.paragraph_format.keep_with_next = True


def apply_run_font(
    run,
    *,
    name: str = "Calibri",
    size: float = 10,
    color: str | None = None,
    bold: bool | None = None,
) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def style_cell_text(
    cell: _Cell,
    *,
    name: str = "Calibri",
    size: float = 10,
    color: str | None = None,
    bold: bool | None = None,
    alignment=None,
) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for paragraph in cell.paragraphs:
        if alignment is not None:
            paragraph.alignment = alignment
        paragraph.paragraph_format.space_after = Pt(0)
        for run in paragraph.runs:
            apply_run_font(
                run,
                name=name,
                size=size,
                color=color,
                bold=bold,
            )


def set_cell_background(cell: _Cell, color: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.insert_element_before(
            shading,
            "w:noWrap",
            "w:tcMar",
            "w:textDirection",
            "w:tcFitText",
            "w:vAlign",
            "w:hideMark",
            "w:tcPrChange",
        )
    shading.set(qn("w:fill"), color)


def set_cell_margins(cell: _Cell, *, top=90, start=100, bottom=90, end=100) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = properties.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        properties.insert_element_before(
            margins,
            "w:textDirection",
            "w:tcFitText",
            "w:vAlign",
            "w:hideMark",
            "w:tcPrChange",
        )
    for edge, value in (("top", top), ("left", start), ("bottom", bottom), ("right", end)):
        element = margins.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            margins.append(element)
        element.set(qn("w:w"), str(value))
        element.set(qn("w:type"), "dxa")


def set_cell_border(cell: _Cell, color: str = LIGHT_BORDER, size: int = 4) -> None:
    properties = cell._tc.get_or_add_tcPr()
    borders = properties.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        properties.insert_element_before(
            borders,
            "w:shd",
            "w:noWrap",
            "w:tcMar",
            "w:textDirection",
            "w:tcFitText",
            "w:vAlign",
            "w:hideMark",
            "w:tcPrChange",
        )
    for edge in ("top", "left", "bottom", "right"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), str(size))
        element.set(qn("w:color"), color)


def format_table_header(table: Table, *, left_aligned_columns=()) -> None:
    row = table.rows[0]
    _set_repeat_table_header(row)
    for index, cell in enumerate(row.cells):
        set_cell_background(cell, NAVY)
        set_cell_border(cell)
        set_cell_margins(cell)
        alignment = (
            WD_ALIGN_PARAGRAPH.LEFT
            if index in left_aligned_columns
            else WD_ALIGN_PARAGRAPH.CENTER
        )
        style_cell_text(
            cell,
            name="Arial",
            size=9,
            color=WHITE,
            bold=True,
            alignment=alignment,
        )


def format_table_body(table: Table, *, start_row: int = 1, font_size: float = 9) -> None:
    for row_index, row in enumerate(table.rows[start_row:]):
        shade = ZEBRA_GRAY if row_index % 2 else WHITE
        _prevent_row_split(row)
        for cell in row.cells:
            set_cell_background(cell, shade)
            set_cell_border(cell)
            set_cell_margins(cell)
            style_cell_text(cell, size=font_size)


def _set_style_font(style, name: str, size: float, *, color=None, bold=None) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    if color:
        style.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        style.font.bold = bold
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def _set_repeat_table_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    properties.append(header)


def _prevent_row_split(row) -> None:
    properties = row._tr.get_or_add_trPr()
    properties.append(OxmlElement("w:cantSplit"))
