from contextlib import closing
from io import StringIO

from PIL import Image, ImageDraw
import pytest

pytest.importorskip("cv2", reason="Install .[structure] for structural detection tests")

from document_to_html import ConversionOptions, OcrOptions, convert
from document_to_html.errors import ConversionError
from document_to_html.ocr import OcrLine, TesseractEngine
from document_to_html.structure import detect_structure
from document_to_html.structured_writer import _render_page


def grid_image():
    image = Image.new("RGB", (800, 1000), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((100, 100, 700, 500), outline="black", width=2)
    # Top row merged across two columns; bottom-left spans two rows.
    drawing.line((100, 200, 700, 200), fill="black", width=2)
    drawing.line((400, 200, 400, 500), fill="black", width=2)
    drawing.line((400, 350, 700, 350), fill="black", width=2)
    return image


def test_detects_merged_rows_and_columns():
    with grid_image() as image:
        structure = detect_structure(image)
    with structure.cleaned:
        assert len(structure.tables) == 1
        table = structure.tables[0]
        assert len(table.cells) == 4
        assert any(cell.colspan == 2 for cell in table.cells)
        assert any(cell.rowspan == 2 for cell in table.cells)
        words = [OcrLine("Heading", 150, 140, 120, 22, 99),
                 OcrLine("<script>alert(1)</script>", 430, 240, 180, 22, 40)]
        stream = StringIO()
        _render_page(stream, structure, words, 800, 1)
        html = stream.getvalue()
        assert 'colspan="2"' in html and 'rowspan="2"' in html
        assert html.count("Heading") == 1
        assert '&lt;script&gt;' in html and '<script>' not in html
        assert 'data-confidence-low="true"' in html
        assert 'contenteditable="plaintext-only"' in html


def test_horizontal_rules_without_grid_remain_css_and_glyph_strokes_survive():
    with Image.new("RGB", (800, 1000), "white") as image:
        draw = ImageDraw.Draw(image)
        draw.line((80, 500, 720, 500), fill="black", width=2)
        draw.line((100, 100, 100, 140), fill="black", width=2)
        structure = detect_structure(image)
    with structure.cleaned:
        assert not structure.tables and structure.rules
        assert structure.cleaned.getpixel((100, 120)) == (0, 0, 0)
        stream = StringIO()
        _render_page(stream, structure, [], 800, 1)
        assert "border-top" in stream.getvalue()
        assert "<img" not in stream.getvalue()


def test_native_pdf_is_visible_readable_without_ocr(source_pdf, monkeypatch):
    def fail(*args):
        raise AssertionError("Native text should not require OCR")
    monkeypatch.setattr(TesseractEngine, "recognize_words", fail)
    result = convert(source_pdf, options=ConversionOptions(output_mode="structured"))
    html = result.output.read_text(encoding="utf-8")
    assert 'Hello HTML 1' in html
    assert 'base64,' not in html and '<svg' not in html
    assert html.count('<section class="page"') == 2
    assert len(html.splitlines()) > 50
    assert not result.ocr_pages


def test_scan_ocr_is_cell_isolated_and_bounded(tmp_path, monkeypatch):
    source = tmp_path / "table.pdf"
    with grid_image() as image:
        image.save(source, "PDF", resolution=100)
    calls = []
    def recognize(self, image):
        calls.append((image.size, self.options.psm))
        return (OcrLine("Test value", 30, 30, 100, 20, 90),)
    monkeypatch.setattr(TesseractEngine, "recognize_words", recognize)
    # Add real content into cells, otherwise blank cells intentionally skip OCR.
    with grid_image() as image:
        draw = ImageDraw.Draw(image)
        for position in ((150, 130), (150, 250), (450, 250), (450, 400)):
            draw.text(position, "Test value", fill="black", font_size=25)
        image.save(source, "PDF", resolution=100)
    result = convert(source, options=ConversionOptions(output_mode="structured", ocr=OcrOptions(dpi=100)))
    assert result.ocr_pages == (1,)
    assert len(calls) >= 5 and calls[0][1] == 6
    assert calls[-1][0] == (800, 1000)
    html = result.output.read_text(encoding="utf-8")
    assert '<table ' in html and 'data:image' not in html


@pytest.mark.parametrize("options", [ConversionOptions(output_mode="bad"),
    ConversionOptions(output_mode="structured", text_layer=False),
    ConversionOptions(output_mode="structured", max_pixels=1)])
def test_invalid_structured_options_preserve_output(source_pdf, options):
    with pytest.raises(ConversionError):
        convert(source_pdf, options=options)
    assert not source_pdf.with_suffix(".html").exists()


def test_structured_ocr_failure_preserves_previous_output(tmp_path, monkeypatch):
    source = tmp_path / "table.pdf"
    output = tmp_path / "keep.html"
    with grid_image() as image:
        image.save(source, "PDF")
    output.write_text("keep")
    def fail(*args):
        raise ConversionError("OCR 逾時")
    monkeypatch.setattr(TesseractEngine, "recognize_words", fail)
    with pytest.raises(ConversionError, match="逾時"):
        convert(source, output, options=ConversionOptions(output_mode="structured", overwrite=True))
    assert output.read_text() == "keep"
    assert not list(tmp_path.glob(".document-to-html-*.tmp"))


def test_structured_browser_edit_print_and_no_network(source_pdf, tmp_path, request):
    channel = request.config.getoption("--browser-channel")
    if not channel:
        pytest.skip("Use --browser-channel for browser tests")
    from scripts.verify_structured import verify
    result = convert(source_pdf, options=ConversionOptions(output_mode="structured"))
    report = verify(result.output, tmp_path / "browser", channel)
    assert report["editable"] and report["network_requests"] == 0
    assert report["print_pages"] == report["pages"] == 2


def test_real_structured_chinese_ocr(tmp_path, request):
    if not request.config.getoption("--ocr-integration"):
        pytest.skip("Use --ocr-integration for real OCR")
    from test_ocr import raster_pdf
    source = raster_pdf(tmp_path / "chinese.pdf", chinese=True)
    result = convert(source, options=ConversionOptions(output_mode="structured", ocr=OcrOptions(psm=6)))
    assert "申購申請書" in result.output.read_text(encoding="utf-8")
