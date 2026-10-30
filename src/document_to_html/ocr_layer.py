"""OCR selection and overlay generation without modifying the displayed image."""

from contextlib import closing
import math

from PIL import ImageDraw
import pypdfium2 as pdfium

from .errors import ConversionError
from .ocr import OcrEngine, OcrOptions
from .visual_text import detect_text_regions, make_recognized_layer


def needs_ocr(page: pdfium.PdfPage, native_count: int, mode: str) -> bool:
    if mode == "off":
        return False
    if mode == "always" or native_count == 0:
        return True
    # Any image (including those nested in forms) can contain scanned text.
    # Avoid interpreting image-object bounds in the wrong form coordinate space.
    return next(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]), None) is not None


def make_ocr_layer(page: pdfium.PdfPage, options: OcrOptions, engine: OcrEngine,
                   max_pixels: int) -> tuple[str, int, int]:
    width, height = page.get_size()
    scale = options.dpi / 72
    if math.ceil(width * scale) * math.ceil(height * scale) > max_pixels:
        raise ConversionError("OCR 頁面影像超過尺寸上限；請降低 --ocr-dpi。")
    with closing(page.render(scale=scale, fill_color=(255, 255, 255, 255))) as bitmap:
        with bitmap.to_pil() as original, original.convert("RGB") as recognition_image:
            regions = detect_text_regions(original, page, bitmap)
            if options.mode == "auto":
                # Mask only the recognition copy. Native text and visible PNG
                # stay intact; a scanned section on the same page remains visible.
                drawing = ImageDraw.Draw(recognition_image)
                coordinates = bitmap.get_posconv(page)
                with closing(page.get_textpage()) as text_page:
                    for index in range(text_page.count_chars()):
                        if not text_page.get_text_range(index, 1).strip():
                            continue
                        left, bottom, right, top = text_page.get_charbox(index)
                        if not all(math.isfinite(value) for value in (left, bottom, right, top)):
                            continue
                        corners = [coordinates.to_bitmap(x, y) for x, y in
                                   ((left, top), (right, top), (left, bottom), (right, bottom))]
                        x0, y0 = max(0, min(x for x, _ in corners) - 2), max(0, min(y for _, y in corners) - 2)
                        x1, y1 = min(bitmap.width - 1, max(x for x, _ in corners) + 2), min(bitmap.height - 1, max(y for _, y in corners) + 2)
                        if x1 >= x0 and y1 >= y0:
                            drawing.rectangle((x0, y0, x1, y1), fill="white")
            lines = engine.recognize(recognition_image)
        layer = make_recognized_layer(lines, bitmap.width, bitmap.height, regions)
        return layer, sum(len(line.text.strip()) for line in lines), sum(line.confidence < 60 for line in lines)
