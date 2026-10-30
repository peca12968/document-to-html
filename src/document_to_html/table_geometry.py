"""Detect axis-aligned rules and bordered cells; no model downloads or network."""

from dataclasses import dataclass

from PIL import Image

from .errors import ConversionError


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    def contains(self, x, y, tolerance=0):
        return (self.left - tolerance <= x <= self.right + tolerance
                and self.top - tolerance <= y <= self.bottom + tolerance)


@dataclass(frozen=True)
class Cell:
    row: int
    column: int
    rowspan: int
    colspan: int
    bounds: Rect


@dataclass(frozen=True)
class Table:
    columns: tuple[int, ...]
    rows: tuple[int, ...]
    cells: tuple[Cell, ...]

    @property
    def bounds(self):
        return Rect(self.columns[0], self.rows[0], self.columns[-1], self.rows[-1])


@dataclass
class Structure:
    tables: tuple[Table, ...]
    rules: tuple[Rect, ...]
    cleaned: Image.Image
    warnings: tuple[str, ...]


def _cluster(values, tolerance):
    groups = []
    for value in sorted(values):
        if groups and value - groups[-1][0] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return tuple(round(sum(group) / len(group)) for group in groups)


def _table(rectangles, tolerance):
    columns = _cluster([x for r in rectangles for x in (r.left, r.right)], tolerance)
    rows = _cluster([y for r in rectangles for y in (r.top, r.bottom)], tolerance)
    if len(columns) * len(rows) > 20_000:
        raise ConversionError("表格結構超過安全上限，請改用高還原模式。")
    occupied = set()
    cells = []
    for rect in sorted(rectangles, key=lambda r: (r.top, r.left)):
        x0, x1 = (min(range(len(columns)), key=lambda i: abs(columns[i] - x)) for x in (rect.left, rect.right))
        y0, y1 = (min(range(len(rows)), key=lambda i: abs(rows[i] - y)) for y in (rect.top, rect.bottom))
        positions = {(row, col) for row in range(y0, y1) for col in range(x0, x1)}
        if not positions or occupied.intersection(positions):
            return None
        occupied.update(positions)
        # Keep exact interior bounds for OCR. Snapped axes are only for HTML
        # layout; using them for crops can put neighboring border pixels back.
        cells.append(Cell(y0, x0, y1 - y0, x1 - x0, rect))
    return Table(columns, rows, tuple(cells))


def detect_structure(image: Image.Image, *, rules_only=False, include_single_cells=False) -> Structure:
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ConversionError('範本模式需要 OpenCV；請執行 python -m pip install -e ".[template]"。') from error
    with image.convert("L") as grayscale:
        gray = np.array(grayscale)
    height, width = gray.shape
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 3)
    if rules_only:
        # Native vector paths contain no character strokes. Join dashed rules
        # before opening, which otherwise removes every individual dash.
        reach = max(3, round(width/250))
        binary = cv2.bitwise_or(
            cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((1,reach),np.uint8)),
            cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((reach,1),np.uint8)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, width // 25), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, height // 120))))
    # Bridge small scan gaps, without treating every character stroke as a rule.
    horizontal = cv2.morphologyEx(horizontal, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    vertical = cv2.morphologyEx(vertical, cv2.MORPH_CLOSE, np.ones((5, 1), np.uint8))
    # Chinese glyphs contain long vertical strokes. Keep short vertical rules
    # only when they meet two horizontal rules; otherwise OCR loses characters.
    candidates, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filtered = np.zeros_like(vertical)
    for candidate in candidates:
        x, y, w, h = cv2.boundingRect(candidate)
        crosses = np.flatnonzero(np.any(horizontal[max(0, y-3):min(height, y+h+3),
                                                  max(0, x-3):min(width, x+w+3)], axis=1))
        joins = len(_cluster(crosses.tolist(), 6))
        if h >= max(80, height // 28) or joins >= 2:
            filtered[y:y+h, x:x+w] = vertical[y:y+h, x:x+w]
    vertical = filtered
    mask = cv2.bitwise_or(horizontal, vertical)
    warnings = []
    # A table continuing onto another PDF page has open verticals at the edge.
    for edge in (0, height - 1):
        xs = np.flatnonzero(vertical[edge])
        if len(xs) > 1 and int(xs[-1] - xs[0]) > width // 5:
            cv2.line(mask, (int(xs[0]), edge), (int(xs[-1]), edge), 255, 2)
            warnings.append("跨頁表格已在頁緣補框，各頁表格獨立，請核對跨頁儲存格。")
    # Scanned border junctions may have a few missing pixels. Extend rules only
    # for topology detection; never erase this extended area from OCR input.
    reach = max(7, round(width / 120))
    connected = cv2.bitwise_or(cv2.dilate(horizontal, np.ones((1, reach), np.uint8)),
                              cv2.dilate(vertical, np.ones((reach, 1), np.uint8)))
    connected = cv2.bitwise_or(connected, mask)
    connected = cv2.dilate(connected, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(connected, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) > 20_000:
        raise ConversionError("偵測到過多線條，請改用高還原模式。")
    groups = {}
    if hierarchy is not None:
        for index, contour in enumerate(contours):
            parent = int(hierarchy[0][index][3])
            if parent < 0:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            # Small checkboxes are symbols, not independent tables.
            if w >= max(25, width // 100) and h >= max(18, height // 200):
                if cv2.contourArea(contour) >= w * h * 0.85:
                    groups.setdefault(parent, []).append(Rect(x, y, x + w - 1, y + h - 1))
    tables = []
    # Native filled borders expose both edges of a thick rule. Snap those edges
    # together so a red overlay does not become an extra, nearly empty column.
    tolerance = max(6, round(width / (160 if rules_only else 200)))
    for rectangles in groups.values():
        if len(rectangles) >= 2 or (include_single_cells and len(rectangles)==1
                                   and rectangles[0].width*rectangles[0].height>width*height*.02):
            table = _table(rectangles, tolerance)
            if table:
                tables.append(table)
            else:
                warnings.append("不規則表格無法可靠合併，內容保留為段落，請人工整理表格。")
    rules = []
    for layer, is_horizontal in ((horizontal, True), (vertical, False)):
        components, _ = cv2.findContours(layer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for component in components:
            x, y, w, h = cv2.boundingRect(component)
            if (is_horizontal and w < width / 8) or (not is_horizontal and h < height / 8):
                continue
            if (is_horizontal and h > max(12, height // 100)) or (not is_horizontal and w > max(12, width // 100)):
                continue
            rect = Rect(x, y, x + w, y + h)
            if not any(table.bounds.contains(x, y, tolerance) and table.bounds.contains(x + w, y + h, tolerance) for table in tables):
                rules.append(rect)
    # Preserve glyphs for OCR. A long CJK stroke can be geometrically identical
    # to a rule; crop cell borders instead of globally deleting line pixels.
    cleaned = image.convert("RGB")
    return Structure(tuple(sorted(tables, key=lambda t: (t.bounds.top, t.bounds.left))),
                     tuple(rules), cleaned, tuple(warnings))
