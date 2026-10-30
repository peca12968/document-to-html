"""Geometry-aware selection layer; shares cell detection with HTML templates.

The page PNG remains the visible document. SVG keeps rotated baselines and exact
character origins without JavaScript, embedded fonts or per-character DOM nodes.
"""

from collections import defaultdict
from contextlib import closing
import ctypes
from dataclasses import dataclass
from html import escape
import math

import pypdfium2 as pdfium

from .errors import ConversionError
from .ocr import _join_words
from .table_geometry import Rect, detect_structure


@dataclass(frozen=True)
class TextRegion:
    bounds: Rect
    table: int
    row: int
    column: int


def detect_text_regions(image, page=None, bitmap=None):
    """Optional template topology; the base installation still converts PDFs."""
    try:
        import cv2  # noqa: F401 - optional template dependency
    except ImportError:
        return ()
    rules_image = None
    try:
        # Native vector rules avoid mistaking Chinese strokes for table lines.
        if page is not None and next(page.get_objects(
                filter=[pdfium.raw.FPDF_PAGEOBJ_FORM], max_depth=1), None) is None:
            from .template_native import native_rules
            rules_image, rules = native_rules(page, bitmap)
            if not rules:
                rules_image.close()
                rules_image = None
        structure = detect_structure(rules_image if rules_image is not None else image,
                                     rules_only=rules_image is not None)
        try:
            return tuple(TextRegion(cell.bounds, table_index, cell.row, cell.column)
                         for table_index, table in enumerate(structure.tables, 1)
                         for cell in table.cells)
        finally:
            structure.cleaned.close()
    except ConversionError:
        # Complex topology must not prevent the fidelity-first mode exporting.
        return ()
    finally:
        if rules_image is not None:
            rules_image.close()


class RegionIndex:
    def __init__(self, regions):
        self.bands = defaultdict(list)
        for region in regions:
            for band in range(region.bounds.top // 64, region.bounds.bottom // 64 + 1):
                self.bands[band].append(region)

    def locate(self, bounds):
        x = (bounds.left + bounds.right) / 2
        y = (bounds.top + bounds.bottom) / 2
        candidates = (region for region in self.bands[int(y) // 64]
                      if region.bounds.contains(x, y, tolerance=2))
        return min(candidates, key=lambda r: r.bounds.width*r.bounds.height, default=None)


@dataclass(frozen=True)
class NativeGlyph:
    text: str
    x: float
    y: float
    angle: float
    size: float
    bounds: Rect

    @property
    def along(self):
        return self.x*math.cos(self.angle) + self.y*math.sin(self.angle)

    @property
    def across(self):
        return -self.x*math.sin(self.angle) + self.y*math.cos(self.angle)


def native_glyphs(page, bitmap):
    coordinates = bitmap.get_posconv(page)
    with closing(page.get_textpage()) as text_page:
        if text_page.count_chars() > 200_000:
            raise ConversionError("單頁文字量超過安全上限（200,000 字元）。")
        for index in range(text_page.count_chars()):
            text = text_page.get_text_range(index, 1)
            if not text or not text.isprintable():
                continue
            bounds = text_page.get_charbox(index, loose=True)
            size = pdfium.raw.FPDFText_GetFontSize(text_page, index)
            angle = pdfium.raw.FPDFText_GetCharAngle(text_page, index)
            origin_x, origin_y = ctypes.c_double(), ctypes.c_double()
            if not pdfium.raw.FPDFText_GetCharOrigin(text_page, index, origin_x, origin_y):
                continue
            if not all(math.isfinite(value) for value in (*bounds, size, angle, origin_x.value, origin_y.value)) or size <= 0:
                continue
            left, bottom, right, top = bounds
            points = [coordinates.to_bitmap(x, y) for x, y in
                      ((left, top), (right, top), (left, bottom), (right, bottom))]
            x, y = coordinates.to_bitmap(origin_x.value, origin_y.value)
            end_x, end_y = coordinates.to_bitmap(origin_x.value + 100*math.cos(angle),
                                                 origin_y.value + 100*math.sin(angle))
            dx, dy = end_x-x, end_y-y
            scale = math.hypot(dx, dy)/100
            yield NativeGlyph(text, x, y, math.atan2(dy, dx), size*scale,
                              Rect(min(p[0] for p in points), min(p[1] for p in points),
                                   max(p[0] for p in points), max(p[1] for p in points)))


def _native_lines(glyphs):
    """Cluster baselines in reading direction, then split columns and font runs."""
    directions = defaultdict(list)
    for glyph in glyphs:
        directions[round(glyph.angle, 2)].append(glyph)
    for items in directions.values():
        rows = []
        for glyph in sorted(items, key=lambda g: (g.across, g.along)):
            row = next((row for row in reversed(rows[-8:])
                        if abs(row[0].across-glyph.across) <= min(row[0].size, glyph.size)*.3), None)
            if row is None:
                rows.append([glyph])
            else:
                row.append(glyph)
        for row in rows:
            run = []
            for glyph in sorted(row, key=lambda g: g.along):
                if run:
                    previous = run[-1]
                    # Source spaces already carry their own origins. A large
                    # empty interval is a separate field, not a stretched line.
                    advance = glyph.along-previous.along
                    if advance > max(previous.size, glyph.size)*2.5 or abs(glyph.size-run[0].size) > run[0].size*.15:
                        yield run
                        run = []
                run.append(glyph)
            if run:
                yield run


def _native_node(glyphs):
    first = glyphs[0]
    dx, dy = math.cos(first.angle), math.sin(first.angle)
    xs = ' '.join(f'{(g.x-first.x)*dx+(g.y-first.y)*dy:.3f}' for g in glyphs for _ in g.text)
    ys = ' '.join(f'{-(g.x-first.x)*dy+(g.y-first.y)*dx:.3f}' for g in glyphs for _ in g.text)
    text = escape(''.join(g.text for g in glyphs))
    return (f'<text class="text-line" x="{xs}" y="{ys}" '
            f'transform="translate({first.x:.4f} {first.y:.4f}) rotate({math.degrees(first.angle):.4f})" '
            f'font-size="{first.size:.4f}">{text}</text>')


def _wrap_layer(width, height, source, groups):
    parts = [f'<svg class="text-layer{ " ocr-layer" if source == "ocr" else ""}" '
             f'data-text-source="{source}" data-layout="regions" '
             f'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none">']
    # Cells stay contiguous in DOM order even when they contain multiple lines.
    for number, (region, bounds, nodes) in enumerate(sorted(groups, key=lambda g: (g[1].top, g[1].left)), 1):
        attributes = (f' data-table="{region.table}" data-row="{region.row+1}" data-column="{region.column+1}"'
                      if region else '')
        parts.append(f'<g class="text-region" data-region="{number}"{attributes}>')
        parts.extend(nodes)
        parts.append('</g>')
    parts.append('</svg>')
    return '\n'.join(parts)


def make_native_layer(page, bitmap):
    with bitmap.to_pil() as image:
        regions = detect_text_regions(image, page, bitmap)
    index = RegionIndex(regions)
    grouped = defaultdict(list)
    count = 0
    for glyph in native_glyphs(page, bitmap):
        grouped[index.locate(glyph.bounds)].append(glyph)
        count += len(glyph.text.strip())
    groups = []
    for region, glyphs in grouped.items():
        lines = list(_native_lines(glyphs))
        lines.sort(key=lambda line: (min(g.bounds.top for g in line), min(g.bounds.left for g in line)))
        if region:
            groups.append((region, region.bounds, [_native_node(line) for line in lines]))
        else:
            for line in lines:
                bounds = Rect(min(g.bounds.left for g in line), min(g.bounds.top for g in line),
                              max(g.bounds.right for g in line), max(g.bounds.bottom for g in line))
                groups.append((None, bounds, [_native_node(line)]))
    return _wrap_layer(bitmap.width, bitmap.height, 'native', groups), count


def make_recognized_layer(lines, width, height, regions=()):
    index = RegionIndex(regions)
    groups = defaultdict(list)
    free = []
    for line in lines:
        runs = []
        for word in line.words or (line,):
            bounds = Rect(word.left, word.top, word.left+word.width, word.top+word.height)
            region = index.locate(bounds)
            if (not runs or runs[-1][0] != region or
                    word.left-(runs[-1][1][-1].left+runs[-1][1][-1].width) > word.height*2):
                runs.append((region, []))
            runs[-1][1].append(word)
        for region, words in runs:
            text = _join_words([word.text for word in words])
            nodes = [f'<text class="text-line" data-confidence="{min(w.confidence for w in words):.2f}" aria-label="{escape(text)}">']
            previous = ''
            for word in words:
                joined = _join_words([previous, word.text]) if previous else word.text
                separator = ' ' if previous and joined == previous+' '+word.text else ''
                nodes.append(separator + f'<tspan x="{word.left}" y="{word.top+word.height}" '
                             f'font-size="{word.height}" textLength="{word.width}" '
                             f'lengthAdjust="spacingAndGlyphs">{escape(word.text)}</tspan>')
                previous = word.text
            nodes.append('</text>')
            node = ''.join(nodes)
            bounds = Rect(min(w.left for w in words), min(w.top for w in words),
                          max(w.left+w.width for w in words), max(w.top+w.height for w in words))
            if region:
                groups[region].append((bounds, node))
            else:
                free.append((None, bounds, [node]))
    result = [(region, region.bounds, [node for bounds, node in sorted(nodes, key=lambda pair: (pair[0].top, pair[0].left))])
              for region, nodes in groups.items()] + free
    return _wrap_layer(width, height, 'ocr', result)
