import json
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from document_to_html import ConversionOptions, OcrOptions, convert
from document_to_html.cli import main
from document_to_html.errors import ConversionError
from scripts.export_demo import FORM
from scripts.export_page_demo import PageMarkup, generate
from scripts.synthetic_pdf import make_pdf


OFF = OcrOptions(mode="off", dpi=96)
FIXTURE = Path(__file__).resolve().parents[1] / "examples/page-selection-demo.json"


@pytest.mark.parametrize("mode", ["visual", "structured"])
def test_page_ranges_are_sorted_deduplicated_and_report_selected_progress(tmp_path, mode):
    source = make_pdf(tmp_path / "many.pdf", pages=7)
    updates = []
    result = convert(source, options=ConversionOptions(dpi=96, pages="6, 2, 5 - 6", max_pages=3,
                     output_mode=mode, ocr=OFF), progress=lambda done, total: updates.append((done, total)))
    markup = PageMarkup(result.output)
    assert [page["number"] for page in markup.pages] == [2, 5, 6]
    assert markup.text == ["Hello HTML 2", "Hello HTML 5", "Hello HTML 6"]
    assert result.pages == 3
    assert updates == [(1, 3), (2, 3), (3, 3)]


def test_unselected_rotated_page_does_not_switch_native_layout(tmp_path):
    rotated = make_pdf(tmp_path / "rotated.pdf", rotation=90, pages=1)
    form = make_pdf(tmp_path / "form.pdf", pages=1, page_content=FORM)
    source = tmp_path / "mixed.pdf"
    with pdfium.PdfDocument(rotated) as cover, pdfium.PdfDocument(form) as page, pdfium.PdfDocument.new() as doc:
        doc.import_pages(cover)
        doc.import_pages(page)
        doc.save(source)
    events = []
    result = convert(source, options=ConversionOptions(output_mode="structured", pages="2", max_pages=1,
                     ocr=OFF), progress=lambda done, total: events.append((done, total)))
    html = result.output.read_text(encoding="utf-8")
    assert [page["number"] for page in PageMarkup(result.output).pages] == [2]
    assert "source-page" in html and "source-table" in html
    assert "Application Form" in html and "Hello HTML 1" not in html
    assert result.pages == 1 and events == [(1, 1)]


def test_ocr_reporting_uses_original_page_numbers_and_skips_other_pages(tmp_path, monkeypatch):
    import document_to_html.html_writer as writer

    rendered = []
    def stub(page, *_):
        with closing(page.get_textpage()) as text_page:
            rendered.append(text_page.get_text_range().strip())
        return "", 0, 1

    monkeypatch.setattr(writer, "make_ocr_layer", stub)
    source = make_pdf(tmp_path / "ocr.pdf", pages=3)
    result = convert(source, options=ConversionOptions(dpi=96, pages="3", ocr=OcrOptions(mode="always")))
    assert rendered == ["Hello HTML 3"]
    assert result.ocr_pages == (3,)
    assert all("第 3 頁" in warning for warning in result.warnings)


@pytest.mark.parametrize("pages, matches", [
    ("", "逗號"), ("0", "從 1"), ("2-1", "終點"), ("1,,2", "逗號"),
    ("3", "只有 2 頁"), ("1,2", "輸出上限"),
])
def test_invalid_selection_preserves_existing_output(source_pdf, pages, matches):
    output = source_pdf.with_suffix(".html")
    output.write_text("old output", encoding="utf-8")
    with pytest.raises(ConversionError, match=matches):
        convert(source_pdf, options=ConversionOptions(overwrite=True, pages=pages, max_pages=1, ocr=OFF))
    assert output.read_text(encoding="utf-8") == "old output"
    assert not list(output.parent.glob(".document-to-html-*.tmp"))


def test_cli_selects_pages_after_word_export(tmp_path, monkeypatch, capsys):
    import document_to_html.converter as converter

    word = tmp_path / "source.docx"
    word.write_bytes(b"test document stub")
    pdf = make_pdf(tmp_path / "export.pdf", pages=3)
    monkeypatch.setattr(converter, "export_word", lambda *_: (pdf, "fixture Word backend"))
    destination = tmp_path / "source.html"
    assert main([str(word), "-o", str(destination), "--pages", "3", "--max-pages", "1", "--ocr", "off"]) == 0
    info = capsys.readouterr()
    assert "1/1" in info.err and "頁數：1" in info.out
    assert PageMarkup(destination).text == ["Hello HTML 3"]


def test_published_example_comes_from_both_actual_outputs(tmp_path):
    assert generate(tmp_path) == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_visual_selection_prints_and_searches_only_selected_source_pages(tmp_path, request):
    channel = request.config.getoption("--browser-channel")
    if not channel:
        pytest.skip("Use --browser-channel chromium or msedge")
    from playwright.sync_api import sync_playwright

    generate(tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel=channel)
        try:
            view = browser.new_page(viewport={"width": 360, "height": 800})
            view.goto((tmp_path / "visual.html").as_uri())
            assert view.evaluate("window.find('Hello HTML 4')")
            assert not view.evaluate("window.find('Hello HTML 3')")
            assert view.locator('.page').evaluate_all("pages => pages.map(p => p.dataset.page)") == ["2", "4"]
            output = view.pdf(prefer_css_page_size=True)
            with pdfium.PdfDocument(output) as printed:
                assert len(printed) == 2
        finally:
            browser.close()
