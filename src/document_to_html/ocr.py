"""Offline Tesseract adapter and validated, pixel-based recognition results."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Protocol

from PIL import Image

from .errors import ConversionError


@dataclass(frozen=True)
class OcrOptions:
    mode: str = "auto"
    language: str = "chi_tra+eng"
    executable: str | None = None
    tessdata: str | None = None
    dpi: int = 300
    timeout: int = 120
    psm: int = 3
    min_confidence: float = 0

    def validate(self) -> None:
        if self.mode not in {"auto", "always", "off"}:
            raise ConversionError("OCR 模式必須為 auto、always 或 off。")
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", self.language):
            raise ConversionError("OCR 語言格式不正確，例如 chi_tra+eng。")
        if not 72 <= self.dpi <= 600 or self.timeout <= 0:
            raise ConversionError("OCR DPI 必須介於 72–600，逾時秒數須大於 0。")
        if self.psm not in {3, 4, 5, 6, 7, 11, 12, 13}:
            raise ConversionError("不支援的 OCR 分頁模式。")
        if not 0 <= self.min_confidence <= 100:
            raise ConversionError("OCR 最低信心分數須介於 0–100。")


@dataclass(frozen=True)
class OcrWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float


@dataclass(frozen=True)
class OcrLine(OcrWord):
    # Keep TSV geometry instead of stretching every word across one line box.
    words: tuple[OcrWord, ...] = field(default=(), kw_only=True)


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> tuple[OcrLine, ...]: ...


def find_tesseract(executable: str | None = None) -> str:
    explicit = executable or os.environ.get("TESSERACT_PATH")
    if explicit:
        resolved = shutil.which(explicit)
        if resolved:
            return resolved
        raise ConversionError("指定的 Tesseract 執行檔不存在。")
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root:
                candidate = Path(root) / "Tesseract-OCR/tesseract.exe"
                if candidate.is_file():
                    return str(candidate)
    raise ConversionError("此頁需要 OCR；請安裝 Tesseract 與 chi_tra、eng 模型，或使用 --ocr off 只保留圖片。")


def _join_words(words: list[str]) -> str:
    # Tesseract splits many CJK characters into separate TSV words. Artificial
    # spaces would break searches for contiguous Chinese phrases.
    result = ""
    cjk = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\U00020000-\U0003134f]")
    for word in words:
        if result and not cjk.search(result[-1]) and not cjk.search(word[0]):
            result += " "
        result += word
    return result


def parse_tsv(data: str, width: int, height: int, minimum: float) -> tuple[OcrLine, ...]:
    groups: dict[tuple[int, ...], list[tuple[str, int, int, int, int, float]]] = {}
    reader = csv.DictReader(StringIO(data.lstrip("\ufeff")), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "page_num", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text"}
    if not required.issubset(reader.fieldnames or []):
        raise ConversionError("Tesseract 回傳的 TSV 格式不完整。")
    for index, row in enumerate(reader):
        if index > 200_000:
            raise ConversionError("OCR 結果超過單頁安全上限。")
        try:
            if row["level"] != "5":
                continue
            text = "".join(character for character in row["text"].strip() if character.isprintable())
            score = float(row["conf"])
            if not text or not math.isfinite(score) or not max(0, minimum) <= score <= 100:
                continue
            x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            if w <= 0 or h <= 0:
                continue
            left, top = max(0, x), max(0, y)
            right, bottom = min(width, x + w), min(height, y + h)
            if right <= left or bottom <= top:
                continue
            key = tuple(int(row[name]) for name in ("page_num", "block_num", "par_num", "line_num"))
            groups.setdefault(key, []).append((text, left, top, right, bottom, score))
        except (ValueError, TypeError, AttributeError) as error:
            raise ConversionError("Tesseract 回傳了無效的文字座標。") from error
    lines = []
    for words in groups.values():
        left, top = min(word[1] for word in words), min(word[2] for word in words)
        right, bottom = max(word[3] for word in words), max(word[4] for word in words)
        # Report the weakest retained word so a mixed-quality line is not hidden
        # by an average dominated by easy words.
        lines.append(OcrLine(_join_words([word[0] for word in words]), left, top,
                             right - left, bottom - top, min(word[5] for word in words),
                             words=tuple(OcrWord(text, x0, y0, x1-x0, y1-y0, score)
                                         for text, x0, y0, x1, y1, score in words)))
    if sum(len(line.text) for line in lines) > 200_000:
        raise ConversionError("OCR 結果超過單頁文字量上限。")
    return tuple(lines)


class TesseractEngine:
    def __init__(self, options: OcrOptions):
        self.options = options
        self._executable: str | None = None

    def _run(self, arguments: list[str], timeout: int) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(arguments, capture_output=True, timeout=timeout, check=False,
                                  **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
        except subprocess.TimeoutExpired as error:
            raise ConversionError("OCR 逾時；請調整 --ocr-timeout 或降低 --ocr-dpi。") from error
        except OSError as error:
            raise ConversionError("無法執行 Tesseract；請檢查執行檔路徑及權限。") from error

    def _prepare(self) -> str:
        if self._executable is not None:
            return self._executable
        self.options.validate()
        executable = find_tesseract(self.options.executable)
        result = self._run([executable, *self._data_arguments(), "--list-langs"], min(self.options.timeout, 15))
        available = set(result.stdout.decode("utf-8", errors="replace").splitlines())
        missing = set(self.options.language.split("+")) - available
        if result.returncode or missing:
            raise ConversionError(f"Tesseract 語言模型不可用：{', '.join(sorted(missing)) or self.options.language}。請安裝模型或指定 --tessdata。")
        self._executable = executable
        return executable

    def _data_arguments(self) -> list[str]:
        return ["--tessdata-dir", self.options.tessdata] if self.options.tessdata else []

    def recognize(self, image: Image.Image) -> tuple[OcrLine, ...]:
        executable = self._prepare()
        with tempfile.TemporaryDirectory(prefix="document-ocr-") as temporary:
            source = Path(temporary) / "page.png"
            with image.convert("RGB") as rgb:
                rgb.save(source, format="PNG", dpi=(self.options.dpi, self.options.dpi))
            result = self._run(
                [executable, str(source), "stdout", *self._data_arguments(),
                 "-l", self.options.language, "--oem", "1", "--psm", str(self.options.psm),
                 "--dpi", str(self.options.dpi), "tsv"], self.options.timeout,
            )
            if result.returncode:
                raise ConversionError("Tesseract 辨識失敗；請檢查模型與影像，或調整 --ocr-psm。")
            if len(result.stdout) > 32 * 1024 * 1024:
                raise ConversionError("OCR 結果超過大小上限。")
            return parse_tsv(result.stdout.decode("utf-8", errors="replace"),
                             image.width, image.height, self.options.min_confidence)
