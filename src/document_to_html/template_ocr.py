"""Isolated, offline OCR for static template analysis.

Use only the models shipped in the pinned RapidOCR wheel. Explicit paths avoid
RapidOCR's automatic model downloader. The subprocess enforces a page deadline.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from PIL import Image

from .errors import ConversionError
from .ocr import OcrLine, OcrOptions


@dataclass(frozen=True)
class RecognizedRegion:
    line: OcrLine
    angle: float = 0.0
    words: tuple[OcrLine, ...] = ()


class TemplateOcr:
    def __init__(self, options: OcrOptions):
        self.options = options

    def recognize(self, image: Image.Image) -> tuple[RecognizedRegion, ...]:
        with tempfile.TemporaryDirectory(prefix="layout-ocr-") as directory:
            source = Path(directory) / "page.png"
            output = Path(directory) / "result.json"
            image.save(source)
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "document_to_html.template_worker", str(source), str(output)],
                    capture_output=True, timeout=self.options.timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as error:
                raise ConversionError("範本 OCR 超過單頁時間上限；請增加 --ocr-timeout。") from error
            if result.returncode or not output.is_file():
                raise ConversionError('範本 OCR 失敗；請安裝 python -m pip install -e ".[template]"。'
                                      "模型必須完整安裝；轉換時不會下載模型。")
            if output.stat().st_size > 20_000_000:
                raise ConversionError("範本 OCR 結果超過安全上限。")
            try:
                return parse_regions(json.loads(output.read_text(encoding="utf-8")),
                                     image.width, image.height, self.options.min_confidence)
            except (ValueError, KeyError, TypeError) as error:
                raise ConversionError("範本 OCR 回傳了無效結果。") from error


def parse_regions(values, width, height, minimum=0, *, allow_words=True):
    import math

    if not isinstance(values, list) or len(values) > 20_000:
        raise ValueError("invalid region count")
    regions = []
    characters = 0
    for value in values:
        text = "".join(c for c in value["text"] if c.isprintable())
        score = float(value["confidence"])
        corners = value["box"]
        if len(corners) != 4 or any(len(p) != 2 for p in corners):
            raise ValueError("invalid quadrilateral")
        coordinates = [float(number) for point in corners for number in point]
        if not all(math.isfinite(number) for number in coordinates + [score]):
            raise ValueError("non-finite coordinate")
        if not 0 <= score <= 100:
            raise ValueError("invalid confidence")
        characters += len(text)
        if characters > 200_000:
            raise ValueError("too much text")
        if not text or score < minimum:
            continue
        left = max(0, math.floor(min(coordinates[::2])))
        top = max(0, math.floor(min(coordinates[1::2])))
        right = min(width, math.ceil(max(coordinates[::2])))
        bottom = min(height, math.ceil(max(coordinates[1::2])))
        if right <= left or bottom <= top:
            continue
        angle = math.degrees(math.atan2(corners[1][1] - corners[0][1], corners[1][0] - corners[0][0]))
        words = ()
        if allow_words and value.get("words"):
            words = tuple(item.line for item in parse_regions(value["words"],width,height,minimum,allow_words=False))
        regions.append(RecognizedRegion(OcrLine(text, left, top, right-left, bottom-top, score), angle, words))
    return tuple(regions)
