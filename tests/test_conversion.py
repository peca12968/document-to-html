import base64
from contextlib import closing
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageChops
import pypdfium2 as pdfium
import pytest

from document_to_html import ConversionOptions, convert
from document_to_html.cli import main
from document_to_html.errors import ConversionError
from conftest import make_pdf


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_lossless_page_pixels_and_rotated_text(tmp_path, rotation):
    source = make_pdf(tmp_path / "rotated.pdf", rotation=rotation)
    result = convert(source, options=ConversionOptions(dpi=144))
    html = result.output.read_text(encoding="utf-8")
    images = re.findall(r'data:image/png;base64,([^\"]+)', html)
    assert len(images) == result.pages == 2
    assert result.text_characters > 0
    assert not result.warnings
    with pdfium.PdfDocument(source) as document:
        document.init_forms()
        for index, data in enumerate(images):
            with closing(document[index]) as page, closing(page.render(scale=2, fill_color=(255, 255, 255, 255))) as bitmap:
                with Image.open(BytesIO(base64.b64decode(data))) as actual, bitmap.to_pil() as expected:
                    assert actual.size == expected.size
                    assert ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).getbbox() is None
    positions = re.findall(r'translate\(([\d.-]+) ([\d.-]+)\)', html)
    assert positions
    assert all(0 <= float(x) <= 640 and 0 <= float(y) <= 640 for x, y in positions)
    assert "Hello HTML 1" in html


def test_existing_output_is_preserved(source_pdf):
    output = source_pdf.with_suffix(".html")
    output.write_text("do not replace")
    with pytest.raises(ConversionError, match="已存在"):
        convert(source_pdf)
    assert output.read_text() == "do not replace"
    convert(source_pdf, options=ConversionOptions(overwrite=True))
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_failure_cleans_temporary_output_and_keeps_existing_file(source_pdf):
    output = source_pdf.with_suffix(".html")
    output.write_text("keep")
    with pytest.raises(ConversionError, match="影像尺寸"):
        convert(source_pdf, options=ConversionOptions(overwrite=True, max_pixels=1))
    assert output.read_text() == "keep"
    assert not list(output.parent.glob(".document-to-html-*.tmp"))


def test_output_created_during_conversion_is_not_overwritten(source_pdf):
    output = source_pdf.with_suffix(".html")
    def concurrent_create(current, total):
        if current == total:
            output.write_text("another writer")
    with pytest.raises(ConversionError, match="已存在"):
        convert(source_pdf, progress=concurrent_create)
    assert output.read_text() == "another writer"


def test_source_cannot_be_overwritten_via_hardlink(source_pdf):
    output = source_pdf.with_suffix(".html")
    output.hardlink_to(source_pdf)
    original = source_pdf.read_bytes()
    with pytest.raises(ConversionError, match="來源"):
        convert(source_pdf, options=ConversionOptions(overwrite=True))
    assert source_pdf.read_bytes() == original


def test_scanned_page_warns_and_no_text_mode_works(tmp_path):
    source = make_pdf(tmp_path / "scan.pdf", text=False)
    result = convert(source)
    assert result.text_characters == 0
    assert len(result.warnings) == 2
    result = convert(source, tmp_path / "image-only.html", options=ConversionOptions(text_layer=False))
    assert not result.warnings
    assert '<svg class="text-layer"' not in result.output.read_text(encoding="utf-8")


@pytest.mark.parametrize("options", [ConversionOptions(dpi=10), ConversionOptions(dpi=601),
    ConversionOptions(backend="unknown"), ConversionOptions(max_pages=1), ConversionOptions(timeout=0)])
def test_invalid_options_and_page_limits(source_pdf, options):
    with pytest.raises(ConversionError):
        convert(source_pdf, options=options)
    assert not source_pdf.with_suffix(".html").exists()


def test_bad_pdf_and_extensions(tmp_path):
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a pdf")
    with pytest.raises(ConversionError, match="PDF 無法開啟"):
        convert(source)
    with pytest.raises(ConversionError, match="找不到"):
        convert(tmp_path / "missing.pdf")
    source = tmp_path / "unsupported.exe"
    source.write_bytes(b"test")
    with pytest.raises(ConversionError, match="僅支援"):
        convert(source)


class TagReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_title_escaped_and_html_has_no_executable_or_remote_content(source_pdf):
    from document_to_html.html_writer import write_html
    from io import StringIO
    stream = StringIO()
    write_html(source_pdf, stream, title='<script>alert("x")</script>', dpi=72,
               text_layer=True, password=None, max_pages=10, max_pixels=1_000_000, progress=None)
    html = stream.getvalue()
    assert "&lt;script&gt;" in html
    parser = TagReader()
    parser.feed(html)
    assert not {"script", "iframe", "object", "embed"}.intersection(tag for tag, _ in parser.tags)
    assert all(not key.startswith("on") for _, attrs in parser.tags for key in attrs)
    assert all(value.startswith("data:image/png;base64,") for _, attrs in parser.tags for key, value in attrs.items() if key == "src")


def test_cli_progress_and_error_exit(source_pdf, capsys):
    assert main([str(source_pdf), "--dpi", "96"]) == 0
    output = capsys.readouterr()
    assert "完成" in output.out and "2/2" in output.err
    assert main([str(source_pdf)]) == 1
