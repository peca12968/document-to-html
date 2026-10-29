"""Readable, standalone static templates. No browser editor or pixel positioning."""

from contextlib import closing
from html import escape
import math
from pathlib import Path
from statistics import median

from PIL import ImageDraw
import pypdfium2 as pdfium

from .errors import ConversionError
from .ocr import OcrOptions
from .ocr_layer import needs_ocr
from .table_geometry import detect_structure
from .template_model import build_page
from .template_ocr import TemplateOcr, RecognizedRegion
from .template_text import _native_words
from .template_images import embedded_image_bounds, find_graphics, image_node
from .template_choices import preserve_choices


def _comment(text):
    return escape(text).replace("--", "—")


def _paragraph(text, symbols=None):
    """Keep meaningful blank runs and recognized choice marks as simple HTML."""
    import re
    symbols = symbols or {}
    pieces = re.split(r"(_{3,}|[□☑☒✅]|\ufff0\d+\ufff1)", text)
    output = []
    for piece in pieces:
        if piece in symbols:
            node = symbols[piece]
            output.append(f'<span class="choice" data-choice="{node["id"]}">'
                          f'<img class="choice-image" src="data:image/png;base64,{node["data"]}" '
                          'alt="原稿勾選框或記號"></span>')
        elif piece.startswith("___"):
            output.append('<span class="blank" aria-label="留白欄位"></span>')
        elif piece in {"□", "☑", "☒", "✅"}:
            output.append(f'<span class="choice-mark">{escape(piece)}</span>')
        else:
            output.append(escape(piece))
    return "".join(output)


class TemplateRenderer:
    """Render a logical model; geometry and recognition are separate concerns."""

    def __init__(self, stream):
        self.stream = stream
        self.symbols = {}

    def text(self, value):
        return _paragraph(value, self.symbols)

    def line(self, indent, text):
        self.stream.write(" " * indent + text + "\n")

    def block(self, node, indent=8, heading=2):
        kind = node["kind"]
        if kind == "paragraph":
            self.line(indent, f'<p>{self.text(node["text"])}</p>')
        elif kind == "field":
            # Values stay text, including account numbers with leading zeroes.
            label = escape(node["label"])
            value = self.text(str(node.get("value", "")))
            unit = escape(node.get("unit", ""))
            self.line(indent, f'<p class="field" data-label="{label}">')
            self.line(indent+4, f'<span class="field-label">{label}：</span>')
            self.line(indent+4, f'<span class="field-value{ " blank" if not value else ""}">{value}</span>{unit}')
            self.line(indent, '</p>')
        elif kind == "fields":
            self.line(indent, '<!-- 基本欄位：保留文字與留白，後續可替換為專案輸入元件。 -->')
            self.line(indent, '<div class="field-grid">')
            for child in node["fields"]:
                self.block(child, indent+4, heading)
            self.line(indent, '</div>')
        elif kind == "section":
            title = node.get("title", "")
            # Unnamed wrappers have no semantic value in the exported source.
            if title:
                self.line(indent, f'<!-- {_comment(title)} -->')
                self.line(indent, f'<section class="document-section" aria-label="{escape(title)}">')
                self.line(indent+4, f'<h{min(heading,6)}>{escape(title)}</h{min(heading,6)}>')
                for child in node["blocks"]:
                    self.block(child, indent+4, heading+1)
                self.line(indent, '</section>')
            else:
                for child in node["blocks"]:
                    self.block(child, indent, heading)
        elif kind == "list":
            self.line(indent, '<ol class="review-list">')
            for item in node["items"]:
                self.line(indent+4, '<li>')
                self.block(item, indent+8, heading)
                self.line(indent+4, '</li>')
            self.line(indent, '</ol>')
        elif kind == "table":
            self.table(node, indent, heading)
        elif kind == "image":
            self.line(indent, f'<figure class="{node["class"]}">')
            self.line(indent+4, f'<img src="data:image/png;base64,{node["data"]}" alt="{escape(node["alt"])}">')
            self.line(indent, '</figure>')
        else:
            raise ConversionError("不支援的範本區塊。")

    def table(self, node, indent, heading):
        self.line(indent, f'<!-- {_comment(node["caption"])} -->')
        self.line(indent, '<table class="document-table">')
        self.line(indent+4, f'<caption>{escape(node["caption"])}</caption>')
        header_count = node.get("header_rows", 0)
        for section, rows in (("thead", node["rows"][:header_count]), ("tbody", node["rows"][header_count:])):
            if not rows:
                continue
            self.line(indent+4, f'<{section}>')
            for row in rows:
                self.line(indent+8, '<tr>')
                for cell in row["cells"]:
                    role = cell.get("role", "cell")
                    tag = "th" if role in {"rowheader", "columnheader"} else "td"
                    attributes = ' scope="col"' if role == "columnheader" else ' scope="row"' if role == "rowheader" else ""
                    for span in ("rowspan", "colspan"):
                        if cell.get(span, 1) > 1:
                            attributes += f' {span}="{int(cell[span])}"'
                    if cell.get("needs_review"):
                        self.line(indent+12, '<!-- 此儲存格邊界由幾何推定，請核對原稿。 -->')
                    blocks = cell["blocks"]
                    if not blocks:
                        self.line(indent+12, f'<{tag}{attributes} class="empty-cell">&nbsp;</{tag}>')
                    elif len(blocks) == 1 and blocks[0]["kind"] == "paragraph":
                        self.line(indent+12, f'<{tag}{attributes}>{self.text(blocks[0]["text"])}</{tag}>')
                    elif len(blocks) == 1 and blocks[0]["kind"] == "field":
                        field = blocks[0]
                        self.line(indent+12, f'<{tag}{attributes}><span class="field-value" '
                                  f'data-label="{escape(field["label"])}">{self.text(field["value"])}</span>'
                                  f'{escape(field.get("unit", ""))}</{tag}>')
                    else:
                        self.line(indent+12, f'<{tag}{attributes}>')
                        for child in blocks:
                            self.block(child, indent+16, heading)
                        self.line(indent+12, f'</{tag}>')
                self.line(indent+8, '</tr>')
            self.line(indent+4, f'</{section}>')
        self.line(indent, '</table>')

    def begin(self, title):
        self.stream.write('<!doctype html>\n<html lang="zh-TW">\n<head>\n'
                          '    <meta charset="utf-8">\n'
                          '    <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                          '    <meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                          'style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'">\n')
        self.line(4, f'<title>{escape(title)}</title>')
        self.line(4, '<style>')
        css = Path(__file__).with_name("resources").joinpath("template.css").read_text(encoding="utf-8")
        for line in css.splitlines():
            self.line(8, line)
        self.line(4, '</style>')
        self.stream.write('</head>\n<body>\n    <main class="document">\n')
        self.line(8, '<!-- 靜態範本：OCR 文字、勾選記號、表格合併及分頁請核對原稿。 -->')
        self.line(8, f'<h1 class="document-title">{escape(title)}</h1>')

    def page(self, page):
        self.symbols = page.get("symbols", {})
        self.line(8, f'<!-- 來源第 {page["number"]} 頁；內容採正常文件流，列印頁數可能改變。 -->')
        self.line(8, f'<article class="document-page" aria-label="來源第 {page["number"]} 頁">')
        for node in page["blocks"]:
            self.block(node, 12)
        self.line(8, '</article>')

    def end(self):
        self.stream.write('    </main>\n</body>\n</html>\n')

    def document(self, title, pages):
        self.begin(title)
        for page in pages:
            self.page(page)
        self.end()


def _extract_title(words, image_width, image_height):
    typical = median([word.height for word in words]) if words else 20
    candidates = [word for word in words if word.top < image_height*.08 and len(word.text) >= 8 and "\ufff0" not in word.text
                  and word.height >= typical*1.05]
    return max(candidates, key=lambda word: word.height / (
        1 + 6*abs(word.left+word.width/2-image_width/2)/image_width), default=None)


def write_template_html(pdf_path, stream, *, title, dpi, text_layer, password,
                        max_pages, max_pixels, progress, ocr=None):
    options = ocr or OcrOptions()
    engine = TemplateOcr(options)
    renderer = TemplateRenderer(stream)
    warnings = ["結構化範本採正常流 HTML/CSS，圖形使用內嵌 PNG。OCR、勾選符號、圖形範圍與儲存格合併需核對；黑白掃描圖形可能需補入，列印頁數可能改變。"]
    ocr_pages = []
    characters = 0
    try:
        document = pdfium.PdfDocument(pdf_path, password=password)
    except pdfium.PdfiumError as error:
        raise ConversionError("PDF 無法開啟，請檢查檔案及密碼。") from error
    with document:
        page_count = len(document)
        if not 0 < page_count <= max_pages:
            raise ConversionError("PDF 頁數超過上限。")
        document.init_forms()
        for index in range(page_count):
            with closing(document[index]) as page:
                width, height = page.get_size()
                scale = options.dpi / 72
                if (not math.isfinite(width*height) or min(width,height) <= 0
                        or math.ceil(width*scale)*math.ceil(height*scale) > max_pixels):
                    raise ConversionError("範本分析影像超過尺寸上限，請降低 --ocr-dpi。")
                with closing(page.render(scale=scale, fill_color=(255,255,255,255))) as bitmap:
                    with bitmap.to_pil().convert("RGB") as image:
                        graphics = find_graphics(image, embedded_image_bounds(page,bitmap))
                        native = _native_words(page, bitmap)
                        native = [word for word in native if not any(bounds.contains(
                            word.left+word.width/2,word.top+word.height/2) for bounds in graphics)]
                        recognized = [] if options.mode == "always" else [RecognizedRegion(word) for word in native]
                        if needs_ocr(page, len(native), options.mode):
                            with image.copy() as recognition:
                                drawing = ImageDraw.Draw(recognition)
                                for bounds in graphics:
                                    drawing.rectangle((bounds.left,bounds.top,bounds.right,bounds.bottom),fill="white")
                                for region in recognized:
                                    word = region.line
                                    drawing.rectangle((word.left-2, word.top-2, word.left+word.width+2,
                                                       word.top+word.height+2), fill="white")
                                recognized.extend(engine.recognize(recognition))
                            ocr_pages.append(index+1)
                        words, symbols = preserve_choices(image,recognized,index+1,graphics)
                        if not words:
                            warnings.append(f"第 {index+1} 頁沒有取得文字，請開啟 OCR 或核對來源。")
                        low_confidence = sum(word.confidence < 85 for word in words)
                        if low_confidence:
                            warnings.append(f"第 {index+1} 頁有 {low_confidence} 個低信心文字區塊。")
                        characters += sum(len(word.text) for word in words if word.text not in symbols)
                        if index == 0:
                            heading = _extract_title(words, image.width, image.height)
                            if heading:
                                title = heading.text
                                words.remove(heading)
                        structure = detect_structure(image)
                        try:
                            image_blocks = [(bounds,image_node(image,bounds,index+1,number))
                                            for number,bounds in enumerate(graphics,1)]
                            model = build_page(structure, words, index+1,image_blocks)
                            if index == 0:
                                renderer.begin(title)
                            renderer.page({"number":index+1, "blocks":model["blocks"], "symbols":symbols})
                            warnings.extend(structure.warnings)
                        finally:
                            structure.cleaned.close()
            if progress:
                progress(index+1, page_count)
        renderer.end()
    return page_count, characters, tuple(warnings), tuple(ocr_pages)
