from contextlib import closing
from io import StringIO
from pathlib import Path

from PIL import Image,ImageDraw
import pypdfium2 as pdfium
import pytest

pytest.importorskip('cv2')

from conftest import make_pdf
from document_to_html import convert,ConversionOptions,OcrOptions
from document_to_html.template_choices import preserve_choices
from document_to_html.template_native import NativeCharacter,NativeRenderer,native_characters,native_rules,supports_native_layout
from document_to_html.template_ocr import RecognizedRegion,TemplateOcr
from document_to_html.table_geometry import detect_structure


@pytest.fixture
def native_form(tmp_path):
    return make_pdf(tmp_path/'native.pdf',pages=2,page_content=b'''
BT /F1 16 Tf 25 290 Td (Application Form) Tj ET
BT /F1 9 Tf 25 270 Td (Please review the form before signing.) Tj ET
1 0 0 RG .8 w 20 60 200 195 re S
0 0 0 RG .5 w 20 220 m 220 220 l S
100 255 m 100 220 l S
[3 2] 0 d 20 180 m 220 180 l S [] 0 d
BT /F1 10 Tf 25 235 Td (Name) Tj ET
BT /F1 10 Tf 105 235 Td (Example) Tj ET
BT /F1 10 Tf 25 200 Td (Signature) Tj ET
BT /F1 9 Tf 25 65 Td (Keep this blank area for signing.) Tj ET
''')


def test_native_form_uses_text_and_vector_cells_without_ocr(native_form,monkeypatch):
    monkeypatch.setattr(TemplateOcr,'recognize',lambda *args:pytest.fail('Native form should not invoke OCR'))
    result=convert(native_form,options=ConversionOptions(output_mode='structured'))
    html=result.output.read_text(encoding='utf-8')
    assert '<title>Application Form</title>' in html
    assert '<colgroup>' in html and '<table class="source-table">' in html
    assert 'Name' in html and 'Example' in html and 'Signature' in html
    assert '#ff0000' in html and 'dashed' in html and 'column-size-' in html
    assert 'position:' not in html and '<input' not in html and '<script' not in html
    assert not result.ocr_pages and result.pages==2
    with pdfium.PdfDocument(native_form) as document,closing(document[0]) as page,closing(page.render(scale=3)) as bitmap:
        characters=native_characters(page,bitmap)
        assert max(word.font_size for word in characters)==16
        rules_image,rules=native_rules(page,bitmap)
        with rules_image:
            structure=detect_structure(rules_image,rules_only=True,include_single_cells=True)
        assert any(rule.dashed for rule in rules)
        assert any(rule.color==(255,0,0) for rule in rules)
        assert structure.tables and any(cell.bounds.height>200 for table in structure.tables for cell in table.cells)
        structure.cleaned.close()


def test_native_layout_force_ocr_and_resource_guard(native_form):
    with pdfium.PdfDocument(native_form) as document:
        assert supports_native_layout(document,'auto')
        assert not supports_native_layout(document,'always')
    from document_to_html.errors import ConversionError
    with pytest.raises(ConversionError,match='尺寸上限'):
        convert(native_form,options=ConversionOptions(output_mode='structured',max_pixels=1))


def test_native_glyph_component_is_not_a_checkbox():
    with Image.new('RGB',(1000,200),'white') as image:
        ImageDraw.Draw(image).rectangle((56,56,76,76),outline='black',width=2)
        glyph=NativeCharacter('回',50,50,40,40,100,12)
        words,symbols=preserve_choices(image,[RecognizedRegion(glyph)],1,strict_text_overlap=True)
    assert words==[glyph] and not symbols


def test_private_font_symbol_is_image_without_choice_state():
    stream=StringIO()
    token='\uffe01\uffe1'
    renderer=NativeRenderer(stream,{token:{'role':'symbol','data':'AA=='}},4)
    text=renderer.rich_text([NativeCharacter(token,0,0,40,40,100,10)])
    assert 'class="source-symbol"' in text and 'data-choice' not in text
    assert token not in text


def test_native_embedded_logo_remains_image(native_form,tmp_path):
    target=tmp_path/'logo.pdf'
    with pdfium.PdfDocument(native_form) as document,closing(document[0]) as page:
        with Image.new('RGB',(100,40),'green') as image,closing(pdfium.PdfBitmap.from_pil(image)) as bitmap:
            logo=pdfium.PdfImage.new(document)
            logo.set_bitmap(bitmap)
            logo.set_matrix(pdfium.PdfMatrix(30,0,0,12,180,285))
            page.insert_obj(logo)
            page.gen_content()
            document.save(target)
    result=convert(target,options=ConversionOptions(output_mode='structured'))
    html=result.output.read_text(encoding='utf-8')
    assert '<figure class="source-figure">' in html and 'data:image/png;base64,' in html
    assert 'Application Form' in html


def test_native_failure_preserves_existing_output(native_form,monkeypatch):
    from document_to_html.errors import ConversionError
    target=native_form.with_suffix('.html');target.write_text('existing',encoding='utf-8')
    def fail(*args,**kwargs): raise ConversionError('render failed')
    monkeypatch.setattr(NativeRenderer,'table',fail)
    with pytest.raises(ConversionError):
        convert(native_form,target,options=ConversionOptions(output_mode='structured',overwrite=True))
    assert target.read_text(encoding='utf-8')=='existing'
    assert not list(native_form.parent.glob('.document-to-html-*.tmp'))


def test_native_browser_pagination_and_editable_flow(native_form,tmp_path,request):
    channel=request.config.getoption('--browser-channel')
    if not channel: pytest.skip('Browser channel not selected')
    from playwright.sync_api import sync_playwright
    result=convert(native_form,options=ConversionOptions(output_mode='structured'))
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel=channel,headless=True)
        page=browser.new_page()
        page.goto(result.output.as_uri())
        assert page.locator('h1').count()==2
        assert page.locator('td').evaluate_all("cells=>cells.some(cell=>getComputedStyle(cell).borderTopColor==='rgb(255, 0, 0)')")
        page.pdf(path=str(tmp_path/'printed.pdf'),prefer_css_page_size=True)
        with pdfium.PdfDocument(tmp_path/'printed.pdf') as printed: assert len(printed)==2
        following=page.locator('article').nth(1)
        before=following.bounding_box()['y']
        page.locator('td').first.evaluate("cell=>cell.textContent+=' Additional text '.repeat(150)")
        assert following.bounding_box()['y']>before
        assert page.locator('input,script,svg,canvas').count()==0
        browser.close()
