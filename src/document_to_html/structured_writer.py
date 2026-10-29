"""Readable HTML tables and CSS rules, with editable visible text.

This is an explicitly approximate reconstruction, not a visual archive or a
business form schema. Every source word is assigned once, by its center point.
"""

from contextlib import closing
from dataclasses import replace
from html import escape
import math
import re
from statistics import median
import time

from PIL import Image, ImageDraw
import pypdfium2 as pdfium

from .errors import ConversionError
from .ocr import OcrLine, OcrOptions, TesseractEngine
from .ocr_layer import needs_ocr
from .structure import detect_structure


STYLE = """
* { box-sizing: border-box; }
body { margin: 0; background: #e9edf3; color: #111; font-family: 'Microsoft JhengHei', sans-serif; }
header { padding: 16px 24px; background: #17283e; color: white; }
h1 { margin: 0 0 8px; font-size: 20px; }
header p { margin: 4px 0; }
main { overflow-x: auto; padding: 20px; }
.page { position: relative; container-type: inline-size; margin: 0 auto 24px; background: white; }
.document-table { position: absolute; border-collapse: collapse; table-layout: fixed; }
.document-table td { border: 1px solid #666; padding: .12cqw; vertical-align: top; overflow-wrap: anywhere; }
.document-table td.unresolved { border: 1px dashed #aaa; }
.cell-text { margin: 0; white-space: pre-wrap; line-height: 1.25; }
.text-block { position: absolute; margin: 0; white-space: pre-wrap; line-height: 1.15; overflow-wrap: anywhere; }
.rule { position: absolute; pointer-events: none; }
[contenteditable]:focus { outline: 2px solid #2376d2; background: #eef6ff; z-index: 2; }
[data-confidence-low="true"] { text-decoration: underline dotted #c47b00; text-underline-offset: 3px; }
.page-note { font-size: 12px; padding: 6px 20px; color: #6b4c00; }
@media print {
  body { background: white; }
  header, .page-note { display: none; }
  main { padding: 0; overflow: visible; }
  .page { margin: 0; break-after: page; break-inside: avoid; }
  .page:last-child { break-after: auto; }
  [contenteditable]:focus { outline: none; background: none; }
  [data-confidence-low="true"] { text-decoration: none; }
}
"""


def _native_words(page, bitmap):
    coordinates = bitmap.get_posconv(page)
    words = []
    current = []

    def flush():
        if not current:
            return
        left, top = min(w.left for w in current), min(w.top for w in current)
        right, bottom = max(w.left + w.width for w in current), max(w.top + w.height for w in current)
        words.append(OcrLine("".join(w.text for w in current), left, top, right-left, bottom-top, 100))
        current.clear()

    with closing(page.get_textpage()) as text_page:
        if text_page.count_chars() > 200_000:
            raise ConversionError("單頁文字量超過安全上限。")
        for index in range(text_page.count_chars()):
            text = text_page.get_text_range(index, 1)
            if not text.strip():
                flush()
                continue
            left, bottom, right, top = text_page.get_charbox(index)
            if not all(math.isfinite(value) for value in (left, bottom, right, top)):
                continue
            corners = [coordinates.to_bitmap(x, y) for x, y in ((left, top), (right, top), (left, bottom), (right, bottom))]
            x0, y0 = max(0, min(x for x, _ in corners)), max(0, min(y for _, y in corners))
            x1, y1 = min(bitmap.width, max(x for x, _ in corners)), min(bitmap.height, max(y for _, y in corners))
            if x1 > x0 and y1 > y0:
                if current:
                    previous = current[-1]
                    if abs(y0 - previous.top) > max(previous.height, y1-y0) or x0 - previous.left - previous.width > previous.height * 2:
                        flush()
                current.append(OcrLine(text, x0, y0, x1 - x0, y1 - y0, 100))
        flush()
    return words


def _lines(words, *, split_gaps=False):
    """Group by geometric baseline within one cell, never across cell borders."""
    rows = []
    for word in sorted(words, key=lambda w: (w.top + w.height / 2, w.left)):
        center = word.top + word.height / 2
        match = next((row for row in reversed(rows[-6:])
                      if abs(center - median(w.top + w.height / 2 for w in row))
                      < max(3, max(word.height, median(w.height for w in row)) * .60)), None)
        if match is None:
            rows.append([word])
        else:
            match.append(word)
    lines = []
    cjk = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\U00020000-\U0003134f]")
    for row in rows:
        chunks = [[]]
        for word in sorted(row, key=lambda w: w.left):
            if chunks[-1] and split_gaps:
                previous = chunks[-1][-1]
                if word.left - previous.left - previous.width > max(previous.height, word.height) * 2:
                    chunks.append([])
            chunks[-1].append(word)
        for chunk in chunks:
            text = ""
            previous = None
            for word in chunk:
                if previous and not cjk.search(previous.text[-1]) and not cjk.search(word.text[0]):
                    if word.left - previous.left - previous.width > min(word.height, previous.height) * .16:
                        text += " "
                text += word.text
                previous = word
            left, top = min(w.left for w in chunk), min(w.top for w in chunk)
            right, bottom = max(w.left + w.width for w in chunk), max(w.top + w.height for w in chunk)
            lines.append(OcrLine(text, left, top, right - left, round(median(w.height for w in chunk)), min(w.confidence for w in chunk)))
    return sorted(lines, key=lambda line: (line.top, line.left))


def _font_size(line, available_width):
    units = sum(1 if ord(char) > 255 else .55 for char in line.text)
    return max(3, min(line.height * 1.05, available_width / max(1, units)))


def _text_markup(line, identifier, width, available_width, *, positioned):
    size = min(3, _font_size(line, available_width) / width * 100)
    low = str(line.confidence < 60).lower()
    style = f"font-size:{size:.4f}cqw;"
    if positioned:
        style += (f"left:{line.left / width * 100:.4f}%;top:{line.top / width * 100:.4f}cqw;"
                  f"width:{available_width / width * 100:.4f}%;")
    return (f'<p id="{identifier}" class="{"text-block" if positioned else "cell-text"}" '
            f'contenteditable="plaintext-only" spellcheck="false" '
            f'data-confidence-low="{low}" style="{style}">{escape(line.text)}</p>')


def _render_page(stream, structure, words, width, page_number):
    assignments = {id(cell): [] for table in structure.tables for cell in table.cells}
    free = []
    for word in words:
        center = word.left + word.width / 2, word.top + word.height / 2
        owner = next((cell for table in structure.tables for cell in table.cells if cell.bounds.contains(*center)), None)
        (assignments[id(owner)] if owner is not None else free).append(word)
    for number, table in enumerate(structure.tables, 1):
        bounds = table.bounds
        stream.write(f'    <!-- 表格 {number}：儲存格 ID 固定於本次輸出，重新辨識可能改變；欄位名稱請由工程師定義。 -->\n')
        stream.write(f'    <table id="page-{page_number}-table-{number}" class="document-table" aria-label="第 {number} 個辨識表格" '
                     f'style="left:{bounds.left / width * 100:.4f}%;top:{bounds.top / width * 100:.4f}cqw;'
                     f'width:{bounds.width / width * 100:.4f}%;">\n      <colgroup>\n')
        for left, right in zip(table.columns, table.columns[1:]):
            stream.write(f'        <col style="width:{(right-left) / bounds.width * 100:.4f}%">\n')
        stream.write('      </colgroup>\n      <tbody>\n')
        starts = {(cell.row, cell.column): cell for cell in table.cells}
        covered = {(r, c) for cell in table.cells for r in range(cell.row, cell.row + cell.rowspan)
                   for c in range(cell.column, cell.column + cell.colspan)}
        for row, (top, bottom) in enumerate(zip(table.rows, table.rows[1:])):
            stream.write(f'        <tr style="height:{(bottom-top) / width * 100:.4f}cqw">\n')
            for column in range(len(table.columns) - 1):
                cell = starts.get((row, column))
                if cell is None:
                    if (row, column) not in covered:
                        stream.write('          <td class="unresolved" title="此區域未辨識到完整儲存格，請核對"></td>\n')
                    continue
                identifier = f"p{page_number}-t{number}-r{row+1}-c{column+1}"
                stream.write(f'          <td id="{identifier}" rowspan="{cell.rowspan}" colspan="{cell.colspan}">\n')
                lines = _lines(assignments[id(cell)])
                for index, line in enumerate(lines, 1):
                    stream.write('            ' + _text_markup(line, f'{identifier}-text-{index}', width,
                                                              max(1, cell.bounds.width - width * .005), positioned=False) + '\n')
                if not lines:
                    empty_size = min(1.3, cell.bounds.height * .35 / width * 100)
                    stream.write(f'            <p id="{identifier}-text-1" class="cell-text" contenteditable="plaintext-only" '
                                 f'aria-label="空白儲存格" style="min-height:0.5em;font-size:{empty_size:.4f}cqw"></p>\n')
                stream.write('          </td>\n')
            stream.write('        </tr>\n')
        stream.write('      </tbody>\n    </table>\n')
    stream.write('    <!-- 未形成完整表格的線段：使用 CSS border；無頁面背景圖片。 -->\n')
    for rule in structure.rules:
        horizontal = rule.width >= rule.height
        border = 'border-top' if horizontal else 'border-left'
        stream.write(f'    <div class="rule" aria-hidden="true" style="left:{rule.left / width * 100:.4f}%;'
                     f'top:{rule.top / width * 100:.4f}cqw;width:{rule.width / width * 100:.4f}%;'
                     f'height:{rule.height / width * 100:.4f}cqw;{border}:1px solid #888;"></div>\n')
    stream.write('    <!-- 表格以外的可見文字區塊 -->\n')
    for index, line in enumerate(_lines(free, split_gaps=True), 1):
        available_width = min(width - line.left, line.width + line.height * .25)
        stream.write('    ' + _text_markup(line, f'p{page_number}-text-{index}', width, available_width, positioned=True) + '\n')


def _recognize_regions(cleaned, structure, engine, options):
    """Isolate detected cells before OCR so words cannot bridge table columns."""
    deadline = time.monotonic() + options.timeout
    cell_engine = TesseractEngine(replace(options, psm=6 if options.psm == 3 else options.psm))

    def recognize(adapter, image):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConversionError("結構化 OCR 超過單頁時間上限；請增加 --ocr-timeout。")
        adapter.options = replace(options, psm=adapter.options.psm, timeout=max(1, math.ceil(remaining)))
        return adapter.recognize_words(image)

    words = []
    cells = [cell for table in structure.tables for cell in table.cells]
    if len(cells) > 1000:
        raise ConversionError("單頁儲存格數超過 1,000；請改用高還原模式。")
    with cleaned.copy() as outside:
        drawing = ImageDraw.Draw(outside)
        for cell in cells:
            bounds = cell.bounds
            left, top = bounds.left + 3, bounds.top + 3
            right, bottom = bounds.right - 3, bounds.bottom - 3
            if right <= left or bottom <= top:
                continue
            with cleaned.crop((left, top, right, bottom)) as crop:
                with crop.convert("L") as gray:
                    blank = gray.getextrema()[0] > 210
                if not blank:
                    # White margins improve recognition of text at cell edges.
                    with Image.new("RGB", (crop.width + 32, crop.height + 32), "white") as padded:
                        padded.paste(crop, (16, 16))
                        for word in recognize(cell_engine, padded):
                            words.append(replace(word, left=word.left + left - 16, top=word.top + top - 16))
            drawing.rectangle((bounds.left, bounds.top, bounds.right, bounds.bottom), fill="white")
        words.extend(recognize(engine, outside))
    return words


def write_structured_html(pdf_path, stream, *, title, dpi, text_layer, password,
                          max_pages, max_pixels, progress, ocr=None):
    ocr = ocr or OcrOptions()
    engine = TesseractEngine(ocr)
    warnings = ["結構化模式為實驗功能：圖片、Logo、印章與手寫筆跡不保留；文字、格線及合併儲存格須核對。",
                "可點文字試改，修改只存在目前頁面，不會自動儲存或回寫 PDF。"]
    ocr_pages = []
    count = 0
    try:
        document = pdfium.PdfDocument(pdf_path, password=password)
    except pdfium.PdfiumError as error:
        raise ConversionError("PDF 無法開啟：檔案可能損毀或需要正確密碼。") from error
    with document:
        if not 0 < len(document) <= max_pages:
            raise ConversionError(f"PDF 頁數必須介於 1 與 {max_pages} 頁之間。")
        document.init_forms()
        stream.write('<!doctype html>\n<html lang="zh-Hant">\n<head>\n  <meta charset="utf-8">\n'
                     '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
                     '  <meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                     'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">\n'
                     f'  <title>{escape(title)} — 結構化 HTML</title>\n  <style>{STYLE}</style>\n</head>\n<body>\n'
                     f'<header><h1>{escape(title)} — 結構化 HTML（實驗）</h1>\n'
                     '<p>可點文字試改；修改不會自動儲存。重新載入會還原，需留存可使用瀏覽器列印。</p>\n'
                     '<p>請核對辨識文字、勾選記號、格線及分頁。Logo、印章與圖片不保留；橙色點線表示低信心文字。</p></header>\n<main>\n')
        for index in range(len(document)):
            with closing(document[index]) as page:
                page_width, page_height = page.get_size()
                scale = ocr.dpi / 72
                if (not math.isfinite(page_width * page_height) or min(page_width, page_height) <= 0
                        or math.ceil(page_width * scale) * math.ceil(page_height * scale) > max_pixels):
                    raise ConversionError(f"第 {index+1} 頁超過影像尺寸上限，請降低 --ocr-dpi。")
                with closing(page.render(scale=scale, fill_color=(255, 255, 255, 255))) as bitmap:
                    with bitmap.to_pil() as image:
                        structure = detect_structure(image)
                    with structure.cleaned as cleaned:
                        native = _native_words(page, bitmap)
                        use_ocr = needs_ocr(page, len(native), ocr.mode)
                        words = [] if ocr.mode == "always" else native
                        if use_ocr:
                            drawing = ImageDraw.Draw(cleaned)
                            for word in words:
                                drawing.rectangle((word.left-2, word.top-2, word.left+word.width+2,
                                                   word.top+word.height+2), fill="white")
                            words = words + _recognize_regions(cleaned, structure, engine, ocr)
                            ocr_pages.append(index + 1)
                    if not words:
                        warnings.append(f"第 {index+1} 頁未取得文字；請啟用 OCR 或核對來源。")
                    low = sum(word.confidence < 60 for word in words)
                    if low:
                        warnings.append(f"第 {index+1} 頁有 {low} 個低信心文字片段，請核對。")
                    warnings.extend(f"第 {index+1} 頁：{message}" for message in structure.warnings)
                    count += sum(len(word.text) for word in words)
                    stream.write(f'  <style>@page sheet{index+1} {{ size:{page_width:.4f}pt {page_height:.4f}pt; margin:0; }}</style>\n'
                                 f'  <section class="page" data-page="{index+1}" aria-label="第 {index+1} 頁" '
                                 f'style="width:{page_width * 96/72:.4f}px;height:{page_height * 96/72:.4f}px;page:sheet{index+1}">\n')
                    _render_page(stream, structure, words, bitmap.width, index + 1)
                    stream.write('  </section>\n')
                if progress:
                    progress(index + 1, len(document))
        stream.write('</main>\n</body>\n</html>\n')
        return len(document), count, tuple(warnings), tuple(ocr_pages)
