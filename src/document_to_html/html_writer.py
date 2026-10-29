"""A static, offline HTML viewer: lossless page image + selectable text overlay."""

from __future__ import annotations

import base64
from contextlib import closing
from html import escape
from io import BytesIO
import math
from pathlib import Path
from typing import Callable, TextIO

import pypdfium2 as pdfium

from .errors import ConversionError
from .ocr import OcrOptions, TesseractEngine
from .ocr_layer import make_ocr_layer, needs_ocr

STYLE = """
*{box-sizing:border-box}body{margin:0;background:#e9edf3;color:#202b3b;font-family:system-ui,sans-serif}
header{padding:18px 24px;background:#17283e;color:white}h1{margin:0;font-size:20px;overflow-wrap:anywhere}
header p{margin:8px 0 0;font-size:13px}main{padding:24px 12px}
.page{position:relative;container-type:inline-size;margin:0 auto 24px;background:white;box-shadow:0 3px 16px #0002;max-width:100%;overflow:hidden}
.page-image{display:block;width:100%;height:100%;user-select:none;pointer-events:none}
.text-layer{position:absolute;inset:0;width:100%;height:100%;overflow:hidden;pointer-events:none}
.text-line{white-space:pre;fill:transparent;cursor:text;user-select:text;pointer-events:all}
.text-line::selection{background:rgba(30,110,230,.3);color:transparent;fill:transparent}
footer{text-align:center;padding:8px 16px 24px;font-size:12px;color:#506070}
@media print{body{background:white}header,footer{display:none}main{padding:0}.page{margin:0;max-width:none;box-shadow:none;break-after:page;break-inside:avoid}.page:last-child{break-after:auto}.text-layer{display:none}}
"""


def _text_layer(page: pdfium.PdfPage, bitmap: pdfium.PdfBitmap) -> tuple[str, int]:
    coordinate_converter = bitmap.get_posconv(page)
    parts = [f'<svg class="text-layer" xmlns="http://www.w3.org/2000/svg" '
             f'viewBox="0 0 {bitmap.width} {bitmap.height}" preserveAspectRatio="none">']
    count = 0
    characters: list[str] = []
    corners: list[tuple[int, int]] = []
    direction = (1.0, 0.0)

    def flush_line() -> None:
        if characters and corners:
            dx, dy = direction
            # Project ink bounds onto baseline and perpendicular axes. SVG's
            # textLength keeps a whole searchable string inside those bounds.
            along = [x * dx + y * dy for x, y in corners]
            across = [-x * dy + y * dx for x, y in corners]
            extent = max(along) - min(along)
            font_size = max(across) - min(across)
            x = dx * min(along) - dy * max(across)
            y = dy * min(along) + dx * max(across)
            if extent > 0 and font_size > 0:
                parts.append(
                    f'<text class="text-line" x="0" y="0" '
                    f'transform="translate({x:.4f} {y:.4f}) rotate({math.degrees(math.atan2(dy, dx)):.4f})" '
                    f'font-size="{font_size:.4f}" textLength="{extent:.4f}" '
                    f'lengthAdjust="spacingAndGlyphs">{escape("".join(characters))}</text>'
                )
        characters.clear()
        corners.clear()

    with closing(page.get_textpage()) as text_page:
        character_count = text_page.count_chars()
        if character_count > 200_000:
            raise ConversionError("單頁文字量超過安全上限（200,000 字元）。")
        for index in range(character_count):
            character = text_page.get_text_range(index, 1)
            if not character or character == "\r":
                continue
            if character == "\n":
                flush_line()
                continue
            if not character.isprintable() and not character.isspace():
                continue
            left, bottom, right, top = text_page.get_charbox(index)
            if not all(math.isfinite(value) for value in (left, bottom, right, top)):
                continue
            if right > left and top > bottom:
                angle = pdfium.raw.FPDFText_GetCharAngle(text_page, index)
                start = coordinate_converter.to_bitmap(left, bottom)
                end = coordinate_converter.to_bitmap(left + 100 * math.cos(angle), bottom + 100 * math.sin(angle))
                delta_x, delta_y = end[0] - start[0], end[1] - start[1]
                magnitude = math.hypot(delta_x, delta_y)
                next_direction = (delta_x / magnitude, delta_y / magnitude) if magnitude else (1.0, 0.0)
                if corners and sum(a * b for a, b in zip(direction, next_direction)) < 0.99:
                    flush_line()
                direction = next_direction
                corners.extend(coordinate_converter.to_bitmap(x, y)
                               for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)))
            characters.append(character)
            count += len(character.strip())
        flush_line()
    parts.append("</svg>")
    return "".join(parts), count


def write_html(
    pdf_path: Path, stream: TextIO, *, title: str, dpi: int,
    text_layer: bool, password: str | None, max_pages: int,
    max_pixels: int, progress: Callable[[int, int], None] | None,
    ocr: OcrOptions | None = None,
) -> tuple[int, int, tuple[str, ...], tuple[int, ...]]:
    ocr = ocr or OcrOptions()
    ocr.validate()
    engine = TesseractEngine(ocr)
    ocr_pages: list[int] = []
    try:
        document = pdfium.PdfDocument(pdf_path, password=password)
    except pdfium.PdfiumError as error:
        raise ConversionError("PDF 無法開啟：檔案可能損毀或需要正確密碼。") from error
    warnings: list[str] = []
    text_characters = 0
    with document:
        page_count = len(document)
        if not 0 < page_count <= max_pages:
            raise ConversionError(f"PDF 頁數必須介於 1 與 {max_pages} 頁之間。")
        document.init_forms()
        stream.write(
            '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            f'<title>{escape(title)}</title><style>{STYLE}</style></head><body>'
            f'<header><h1>{escape(title)}</h1><p>{page_count} 頁 · {dpi} DPI · '
            '離線高還原 HTML · 可使用瀏覽器列印或搜尋</p></header><main>'
        )
        for index in range(page_count):
            with closing(document[index]) as page:
                width, height = page.get_size()
                scale = dpi / 72
                if (not math.isfinite(width * height) or width <= 0 or height <= 0
                        or math.ceil(width * scale) * math.ceil(height * scale) > max_pixels):
                    raise ConversionError(f"第 {index + 1} 頁超過影像尺寸上限，請降低 DPI。")
                with closing(page.render(scale=scale, fill_color=(255, 255, 255, 255))) as bitmap:
                    with bitmap.to_pil() as image, BytesIO() as buffer:
                        image.save(buffer, format="PNG")
                        encoded_image = base64.b64encode(buffer.getvalue()).decode("ascii")
                    layer, count = _text_layer(page, bitmap) if text_layer else ("", 0)
                if text_layer and needs_ocr(page, count, ocr.mode):
                    ocr_layer, ocr_count, low_confidence = make_ocr_layer(page, ocr, engine, max_pixels)
                    ocr_pages.append(index + 1)
                    if ocr.mode == "always" or count == 0:
                        layer, count = ocr_layer, ocr_count
                    else:
                        layer, count = layer + ocr_layer, count + ocr_count
                    if low_confidence:
                        warnings.append(f"第 {index + 1} 頁有 {low_confidence} 行 OCR 文字信心分數低於 60，請核對複製內容。")
                text_characters += count
                if text_layer and count == 0:
                    detail = "OCR 未辨識出可用文字" if index + 1 in ocr_pages else "OCR 已關閉"
                    warnings.append(f"第 {index + 1} 頁沒有可擷取文字；已保留影像，{detail}。")
                page_name = f"sheet{index + 1}"
                stream.write(
                    f'<style>@page {page_name}{{size:{width:.4f}pt {height:.4f}pt;margin:0}}</style>'
                    f'<section class="page" aria-label="第 {index + 1} 頁" '
                    f'data-page="{index + 1}" '
                    f'style="width:{width * 96 / 72:.4f}px;aspect-ratio:{width}/{height};page:{page_name}">'
                    f'<img class="page-image" alt="" aria-hidden="true" '
                    f'width="{math.ceil(width * scale)}" height="{math.ceil(height * scale)}" '
                    f'src="data:image/png;base64,{encoded_image}">{layer}</section>'
                )
                if progress:
                    progress(index + 1, page_count)
        if ocr_pages:
            stream.write(f'<footer>已對 {len(ocr_pages)} 頁執行 OCR；辨識文字可能有誤，請以原始影像為準。</footer>')
        stream.write('</main><footer>原始頁面外觀採用無損影像；文字層供選取與搜尋，非可編輯表格。</footer></body></html>')
    return page_count, text_characters, tuple(warnings), tuple(ocr_pages)
