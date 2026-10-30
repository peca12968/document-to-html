"""Selection geometry, cell reading order and graceful optional-dependency use."""

import builtins
from html.parser import HTMLParser

from PIL import Image
import pytest

from document_to_html import ConversionOptions, OcrOptions, convert
from document_to_html.ocr import OcrLine, OcrWord
from document_to_html.table_geometry import Rect
from document_to_html.visual_text import (TextRegion, detect_text_regions,
                                         make_recognized_layer)
from conftest import make_pdf


class LayerReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.regions = []
        self.current = None
        self.lines = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'g':
            self.current = [attrs, '']
            self.regions.append(self.current)
        if tag == 'text':
            self.lines.append(attrs)

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == 'g':
            self.current = None


def test_native_cell_order_and_individual_origins(tmp_path):
    pytest.importorskip('cv2')
    # PDF object order is deliberately different from cell reading order.
    content = (b'0 G 1 w 20 100 200 180 re S 120 100 m 120 280 l S\n'
               b'BT /F1 12 Tf 130 250 Td (Right 1) Tj ET\n'
               b'BT /F1 12 Tf 30 220 Td (Left 2) Tj ET\n'
               b'BT /F1 12 Tf 30 250 Td (Left 1) Tj ET\n'
               b'BT /F1 12 Tf 130 220 Td (Right 2) Tj ET\n')
    source = make_pdf(tmp_path/'cells.pdf', pages=1, page_content=content)
    result = convert(source, options=ConversionOptions(ocr=OcrOptions(mode='off')))
    reader = LayerReader()
    reader.feed(result.output.read_text(encoding='utf-8'))
    cells = [(attrs, text) for attrs, text in reader.regions if 'data-column' in attrs]
    assert len(cells) == 2
    assert 'Left 1' in cells[0][1] and 'Left 2' in cells[0][1]
    assert 'Right' not in cells[0][1]
    assert cells[0][1].index('Left 1') < cells[0][1].index('Left 2')
    assert 'Right 1' in cells[1][1] and 'Right 2' in cells[1][1]
    assert all(len(line['x'].split()) > 1 for line in reader.lines)
    assert all('textLength' not in line for line in reader.lines)


def test_ocr_cells_split_even_when_tesseract_reports_one_line():
    words = (OcrWord('左欄', 10, 10, 30, 20, 95),
             OcrWord('右欄', 120, 10, 30, 20, 55))
    regions = (TextRegion(Rect(0, 0, 100, 60), 1, 0, 0),
               TextRegion(Rect(100, 0, 200, 60), 1, 0, 1))
    html = make_recognized_layer((OcrLine('左欄右欄', 10, 10, 140, 20, 55, words=words),), 200, 100, regions)
    reader = LayerReader()
    reader.feed(html)
    assert len(reader.regions) == 2
    assert reader.regions[0][1].strip() == '左欄'
    assert reader.regions[1][1].strip() == '右欄'
    assert 'x="120"' in html and 'textLength="30"' in html
    assert 'data-confidence="55.00"' in html


def test_large_ocr_gap_splits_without_table_detection():
    words = (OcrWord('Account', 10, 10, 70, 20, 99),
             OcrWord('Total', 300, 10, 50, 20, 99))
    html = make_recognized_layer((OcrLine('Account Total', 10, 10, 340, 20, 99, words=words),), 400, 100)
    reader = LayerReader()
    reader.feed(html)
    assert len(reader.regions) == 2


def test_text_fidelity_and_search_across_ocr_words(tmp_path, request):
    channel = request.config.getoption('--browser-channel')
    if not channel:
        pytest.skip('Requires a browser channel')
    words = (OcrWord('申購', 10, 10, 40, 25, 95),
             OcrWord('申請書', 50, 10, 60, 25, 95))
    html = make_recognized_layer((OcrLine('申購申請書', 10, 10, 100, 25, 95, words=words),), 200, 100)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page()
        page.set_content('<style>.text-line{fill:transparent;user-select:text}</style>'+html)
        assert page.evaluate("window.find('申購申請書')")
        assert page.evaluate('window.getSelection().toString()') == '申購申請書'
        boxes = page.locator('tspan').evaluate_all('nodes => nodes.map(n => {const b=n.getBBox(); return [b.x,b.width]})')
        assert boxes[0][0] == pytest.approx(10, abs=1)
        assert boxes[1][0] == pytest.approx(50, abs=1)
        browser.close()


def test_missing_opencv_does_not_block_visual_conversion(source_pdf, monkeypatch):
    original = builtins.__import__
    def without_cv2(name, *args, **kwargs):
        if name == 'cv2':
            raise ImportError('optional dependency absent')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_cv2)
    with Image.new('RGB', (200, 100), 'white') as image:
        assert detect_text_regions(image) == ()
    result = convert(source_pdf)
    assert 'Hello HTML 1' in result.output.read_text(encoding='utf-8')


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_native_search_and_copy_with_rotated_page(tmp_path, request, rotation):
    channel = request.config.getoption('--browser-channel')
    if not channel:
        pytest.skip('Requires a browser channel')
    source = make_pdf(tmp_path/'rotated.pdf', pages=1, rotation=rotation)
    result = convert(source)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page()
        page.goto(result.output.as_uri())
        assert page.evaluate("window.find('Hello HTML 1')")
        assert page.evaluate('window.getSelection().toString()') == 'Hello HTML 1'
        # Native per-character origins survive the page rotation and scaling.
        positions = page.locator('.text-line').first.evaluate('n => Array.from({length:n.getNumberOfChars()}, (_,i) => n.getStartPositionOfChar(i).x)')
        assert positions == sorted(positions)
        browser.close()
