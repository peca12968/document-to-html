"""Conversion orchestration, validation and atomic output publication."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Callable

import pypdfium2 as pdfium

from .backends import export_word
from .errors import ConversionError
from .html_writer import write_html
from .ocr import OcrOptions
from .structured_writer import write_structured_html
from .layout_writer import write_layout_html


@dataclass(frozen=True)
class ConversionOptions:
    dpi: int = 200
    text_layer: bool = True
    backend: str = "auto"
    libreoffice: str | None = None
    timeout: int = 120
    overwrite: bool = False
    max_pages: int = 200
    max_pixels: int = 50_000_000
    max_input_bytes: int = 100 * 1024 * 1024
    ocr: OcrOptions = field(default_factory=OcrOptions)
    output_mode: str = "visual"

    def validate(self) -> None:
        self.ocr.validate()
        if self.output_mode not in {"visual", "structured", "layout"}:
            raise ConversionError("輸出模式必須為 visual、structured 或 layout。")
        if self.output_mode in {"structured", "layout"} and not self.text_layer:
            raise ConversionError("結構化模式需要可見文字，不能與 --no-text-layer 同時使用。")
        if not 72 <= self.dpi <= 600:
            raise ConversionError("DPI 必須介於 72 與 600。")
        if self.backend not in {"auto", "word", "libreoffice"}:
            raise ConversionError("不支援的 Word 轉檔引擎。")
        if min(self.timeout, self.max_pages, self.max_pixels, self.max_input_bytes) <= 0:
            raise ConversionError("時間與資源上限必須大於 0。")


@dataclass(frozen=True)
class ConversionResult:
    output: Path
    pages: int
    text_characters: int
    backend: str
    warnings: tuple[str, ...]
    ocr_pages: tuple[int, ...] = ()
    assets: Path | None = None


def convert(
    source: str | Path, output: str | Path | None = None, *,
    options: ConversionOptions | None = None, password: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ConversionResult:
    """Convert one document. Serialize concurrent calls: PDFium is not thread-safe."""
    options = options or ConversionOptions()
    options.validate()
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ConversionError("找不到輸入檔案。")
    if source.suffix.lower() not in {".pdf", ".doc", ".docx"}:
        raise ConversionError("僅支援 .pdf、.doc、.docx 檔案。")
    if not 0 < source.stat().st_size <= options.max_input_bytes:
        raise ConversionError("輸入檔案為空或超過大小上限（預設 100 MiB）。")
    destination = Path(output).expanduser().resolve() if output else source.with_suffix(".html")
    if destination.suffix.lower() not in {".html", ".htm"}:
        raise ConversionError("輸出副檔名必須為 .html 或 .htm。")
    if destination == source or (destination.exists() and os.path.samefile(source, destination)):
        raise ConversionError("輸出不可覆蓋來源檔案。")
    if destination.exists() and not options.overwrite:
        raise ConversionError("輸出檔案已存在；請更名或使用 --overwrite。")
    temporary_output: Path | None = None
    published_assets: Path | None = None
    completed = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="document-to-html-") as temporary_directory:
            backend_name = "PDFium"
            pdf_path = source
            if source.suffix.lower() != ".pdf":
                pdf_path, backend_name = export_word(
                    source, Path(temporary_directory), options.backend,
                    options.timeout, options.libreoffice,
                )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", prefix=".document-to-html-",
                suffix=".tmp", dir=destination.parent, delete=False,
            ) as stream:
                temporary_output = Path(stream.name)
                writer = {"visual": write_html, "structured": write_structured_html, "layout": write_layout_html}[options.output_mode]
                extra = {}
                if options.output_mode == "layout":
                    # Own a fresh assets directory for this conversion. Existing
                    # HTML/asset versions are untouched until HTML publication.
                    candidate = destination.parent / f"{destination.stem}-assets-{uuid.uuid4().hex[:12]}"
                    candidate.mkdir()
                    published_assets = candidate
                    extra = {"assets_directory": published_assets, "assets_name": published_assets.name}
                pages, text_characters, warnings, ocr_pages = writer(
                    pdf_path, stream, title=source.stem, dpi=options.dpi,
                    text_layer=options.text_layer, password=password,
                    max_pages=options.max_pages, max_pixels=options.max_pixels, progress=progress,
                    ocr=options.ocr,
                    **extra,
                )
            if options.overwrite:
                os.replace(temporary_output, destination)
            else:
                # Atomic no-clobber: a file created during conversion is protected too.
                os.link(temporary_output, destination)
            completed = True
            return ConversionResult(destination, pages, text_characters, backend_name, warnings, ocr_pages, published_assets)
    except FileExistsError as error:
        raise ConversionError("輸出檔案已存在；未覆蓋既有資料。") from error
    except (OSError, pdfium.PdfiumError) as error:
        raise ConversionError(f"轉換失敗（{type(error).__name__}）；請檢查檔案、權限及磁碟空間。") from error
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)
        if not completed and published_assets is not None:
            # Only the fresh, uniquely named directory created above is removed.
            shutil.rmtree(published_assets, ignore_errors=True)
