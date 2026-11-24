"""Parse 1-based page numbers and resolve them against the exported PDF."""
from __future__ import annotations

import re

from .errors import ConversionError


def parse_page_ranges(selection: str | None) -> tuple[tuple[int, int], ...] | None:
    if selection is None:
        return None
    if not isinstance(selection, str):
        raise ConversionError("頁碼請使用逗號分隔，例如 2,5-7。")
    ranges = []
    for part in selection.split(","):
        match = re.fullmatch(r"([0-9]{1,10})(?:\s*-\s*([0-9]{1,10}))?", part.strip())
        if not match:
            raise ConversionError("頁碼請使用逗號分隔，例如 2,5-7。")
        first = int(match[1])
        last = int(match[2]) if match[2] else first
        if not 1 <= first <= last:
            raise ConversionError("頁碼從 1 開始，範圍終點不得小於起點。")
        ranges.append((first, last))
    return tuple(ranges)


def select_indices(count, max_pages, ranges):
    if ranges is None:
        if not 0 < count <= max_pages:
            raise ConversionError(f"PDF 頁數必須介於 1 與 {max_pages} 頁之間。")
        return range(count)

    selected = set()
    for first, last in ranges:
        if last > count:
            raise ConversionError(f"指定第 {last} 頁，但來源 PDF 只有 {count} 頁。")
        if last - first + 1 > max_pages:
            raise ConversionError(f"選取頁數超過 {max_pages} 頁的輸出上限。")
        selected.update(range(first - 1, last))
        if len(selected) > max_pages:
            raise ConversionError(f"選取頁數超過 {max_pages} 頁的輸出上限。")
    return sorted(selected)
