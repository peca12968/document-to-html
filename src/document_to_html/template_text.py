"""Native text extraction and baseline grouping used only during analysis."""

from contextlib import closing
import math
import re
from statistics import median
from .ocr import OcrLine
from .errors import ConversionError


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
                if previous:
                    gap = word.left - previous.left - previous.width
                    if gap > max(previous.height, word.height) * 2 and not previous.text.endswith(("：", ":")):
                        text += "  "
                    elif not cjk.search(previous.text[-1]) and not cjk.search(word.text[0]) and gap > min(word.height, previous.height) * .16:
                        text += " "
                text += word.text
                previous = word
            left, top = min(w.left for w in chunk), min(w.top for w in chunk)
            right, bottom = max(w.left + w.width for w in chunk), max(w.top + w.height for w in chunk)
            lines.append(OcrLine(text, left, top, right - left, round(median(w.height for w in chunk)), min(w.confidence for w in chunk)))
    # Rows are already in baseline order. Sorting chunks by their individual
    # top edges can place a slightly taller value before its label.
    return lines
