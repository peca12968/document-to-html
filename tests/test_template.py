from io import StringIO
from pathlib import Path

from PIL import Image
import pytest

pytest.importorskip("cv2", reason="Install .[template] to test static templates")

from document_to_html import ConversionOptions, OcrOptions, convert
from document_to_html.errors import ConversionError
from document_to_html.ocr import OcrLine
from document_to_html.table_geometry import Cell, Rect, Structure, Table
from document_to_html.template_model import build_page, normalize_table, organize_prose, table_model
from document_to_html.template_ocr import RecognizedRegion, TemplateOcr, parse_regions
from document_to_html.template_choices import preserve_choices
from document_to_html.template_writer import TemplateRenderer
from document_to_html.template_text import _lines
from document_to_html.template_images import find_graphics, image_node


def word(text, left, top, width=60, height=20):
    return OcrLine(text, left, top, width, height, 99)


def test_label_value_grid_exports_static_placeholders():
    table = Table((0,100,300), (0,50,100), tuple(
        Cell(row,column,1,1,Rect(left,top,right,top+50))
        for row,top in enumerate((0,50)) for column,(left,right) in enumerate(((0,100),(100,300)))))
    model, leftover = table_model(table, [word("姓名",10,10), word("編號",10,60), word("000123",110,60)], "details")
    assert not leftover
    stream = StringIO()
    TemplateRenderer(stream).block(model)
    html = stream.getvalue()
    assert 'data-label="姓名"' in html and 'class="field-value blank"' in html
    assert "000123" in html and "<input" not in html and "contenteditable" not in html


def test_prose_becomes_nested_sections_and_lists_without_business_templates():
    paragraphs = [{"kind":"paragraph", "text":text} for text in (
        "一、申請資料", "姓名：測試員", "第二部分：確認事項", "（一）已閱讀文件。", "（二）已確認內容。")]
    blocks = organize_prose(paragraphs, "page-1")
    assert blocks[0]["title"] == "一、申請資料"
    children = blocks[0]["blocks"]
    assert children[0]["kind"] == "fields"
    assert children[1]["title"] == "第二部分：確認事項"
    assert len(children[1]["blocks"][0]["items"]) == 2


def test_scan_gap_does_not_merge_actual_comparison_rows():
    table = Table((0,100,200),(0,60,65,125),(
        Cell(0,0,3,1,Rect(0,0,100,125)), Cell(0,1,1,1,Rect(100,0,200,60)),
        Cell(2,1,1,1,Rect(100,65,200,125))))
    normalized = normalize_table(table,40)
    assert len(normalized.rows) == 3 and len(normalized.cells) == 3
    assert normalized.cells[0].rowspan == 2


def test_baseline_order_keeps_labels_values_and_choices_together():
    lines = _lines([word("金額：",10,12,80,20),word("2,000,000",220,10,100,24),
                    word("序號：001",440,10,100,24),word("下一行",10,50)],split_gaps=False)
    assert lines[0].text.replace(" ", "") == "金額：2,000,000序號：001"
    blocks = organize_prose([{"kind":"paragraph","text":line.text} for line in lines],"sample")
    assert blocks[0]["fields"][0]["value"] == "2,000,000"
    assert blocks[0]["fields"][1]["value"] == "001"
    separated = _lines([word("類別：一般貸款",10,10,120),word("型態：定儲指數",400,10,120)])
    fields = organize_prose([{"kind":"paragraph","text":separated[0].text}],"sample")[0]["fields"]
    assert [(field["label"],field["value"]) for field in fields] == [("類別","一般貸款"),("型態","定儲指數")]


def test_unclosed_cell_keeps_text_and_emits_review_comment():
    table = Table((0,100,200),(0,80),(Cell(0,0,1,1,Rect(0,0,100,80)),))
    with Image.new("RGB",(220,100),"white") as cleaned:
        model = build_page(Structure((table,),(),cleaned,()), [word("Label",5,10),word("Unclosed",110,10)],1)
    stream = StringIO()
    TemplateRenderer(stream).block(model)
    assert "Unclosed" in stream.getvalue()


def test_document_escapes_ocr_text_and_contains_no_editor_or_positioned_elements():
    stream = StringIO()
    TemplateRenderer(stream).document('<script>alert(1)</script>', [{"number":1,"blocks":[
        {"kind":"section","title":"x --> <script>","blocks":[
            {"kind":"paragraph","text":'姓名___ □同意 <img src=x onerror=alert(1)>'}]}]}])
    html = stream.getvalue()
    assert "&lt;script&gt;" in html and "<script>" not in html and "<img " not in html
    assert 'class="blank"' in html and 'class="choice-mark"' in html
    assert "position:" not in html and "contenteditable" not in html and "@@page" not in html
    assert '<section class="document-section"' in html and '@page' in html


def test_native_template_uses_no_ocr_and_does_not_overwrite_visual(source_pdf,monkeypatch):
    def fail(*args):
        raise AssertionError("Native text must not require OCR")
    monkeypatch.setattr(TemplateOcr,"recognize",fail)
    visual = source_pdf.with_suffix(".html")
    visual.write_text("keep visual",encoding="utf-8")
    result = convert(source_pdf,options=ConversionOptions(output_mode="structured",ocr=OcrOptions(dpi=100)))
    html = result.output.read_text(encoding="utf-8")
    assert result.output.name.endswith("-template.html")
    assert "Hello HTML 1" in html and "Hello HTML 2" in html
    assert "base64," not in html and "<svg" not in html and "<script" not in html
    assert not result.ocr_pages and visual.read_text(encoding="utf-8") == "keep visual"


@pytest.mark.parametrize("options", [ConversionOptions(output_mode="invalid"),
    ConversionOptions(output_mode="structured",text_layer=False),
    ConversionOptions(output_mode="structured",max_pixels=1)])
def test_invalid_mode_and_resource_limit(source_pdf,options):
    with pytest.raises(ConversionError):
        convert(source_pdf,options=options)


def test_template_failure_does_not_replace_existing_html(source_pdf,monkeypatch):
    destination = source_pdf.with_suffix(".html")
    destination.write_text("keep",encoding="utf-8")
    def fail(*args,**kwargs):
        raise ConversionError("failed")
    monkeypatch.setattr(TemplateRenderer,"begin",fail)
    with pytest.raises(ConversionError):
        convert(source_pdf,destination,options=ConversionOptions(output_mode="structured",overwrite=True))
    assert destination.read_text(encoding="utf-8") == "keep"
    assert not list(source_pdf.parent.glob(".document-to-html-*.tmp"))


def test_invalid_ocr_result_is_rejected():
    with pytest.raises(ValueError):
        parse_regions([{"text":"x","confidence":99,"box":[[0,0],[float('nan'),0],[1,1],[0,1]]}],100,100)


def test_logo_is_embedded_png_but_tiny_tick_and_long_rule_are_not():
    from PIL import ImageDraw
    import base64
    from io import BytesIO
    with Image.new("RGB",(1000,1400),"white") as image:
        drawing = ImageDraw.Draw(image)
        drawing.ellipse((50,50,110,110),fill="green")
        drawing.rectangle((115,60,230,85),fill="black")
        drawing.line((300,300,308,310,320,290),fill="blue",width=3)
        drawing.line((50,400,950,400),fill="red",width=3)
        graphics = find_graphics(image)
        assert len(graphics) == 1
        bounds = graphics[0]
        assert bounds.contains(180,70) and bounds.width<image.width/2
        node = image_node(image,bounds,1,1)
        decoded = Image.open(BytesIO(base64.b64decode(node["data"])))
        assert decoded.format == "PNG" and decoded.size == (bounds.width,bounds.height)
        stream = StringIO()
        TemplateRenderer(stream).document("範本",[{"number":1,"blocks":[node]}])
        assert '<img src="data:image/png;base64,' in stream.getvalue()
        assert "img-src data:" in stream.getvalue()


def test_image_inside_table_is_retained_in_cell():
    table = Table((0,100,200),(0,100),tuple(Cell(0,col,1,1,Rect(col*100,0,(col+1)*100,100)) for col in range(2)))
    node = {"kind":"image","data":"AA==","alt":"圖片","class":"document-image"}
    model, _ = table_model(table,[word("說明",10,10)],"t1",[(Rect(110,10,160,60),node)])
    assert model["kind"] == "table"
    assert node in model["rows"][0]["cells"][1]["blocks"]


def test_choice_images_preserve_original_pixels_without_checked_state():
    from PIL import ImageDraw
    from io import BytesIO
    import base64

    with Image.new("RGB", (1000,500), "white") as image:
        drawing=ImageDraw.Draw(image)
        for left in (50,120,200):
            drawing.rectangle((left,50,left+20,70),outline="black",width=2)
        drawing.line((123,60,130,67,137,47),fill="blue",width=2)
        drawing.line((300,60,306,68,318,50),fill="blue",width=2)
        regions=[RecognizedRegion(word("□同意",50,48,65,24), words=(
            word("□",50,48,21,24),word("同",76,48,20,24),word("意",96,48,20,24))),
            RecognizedRegion(word("☑",120,48,21,24)),
            RecognizedRegion(word("口",200,48,21,24)),
            RecognizedRegion(word("✓",300,48,20,24))]
        words,symbols=preserve_choices(image,regions,1)
        assert len(symbols)==3  # Empty box, checked box, free-standing tick; not 口.
        assert {"同","意","口"} <= {item.text for item in words}
        assert not any(item.text in {"□","☑","✓"} for item in words)
        for node in symbols.values():
            with Image.open(BytesIO(base64.b64decode(node["data"]))) as crop:
                assert crop.width<40 and crop.height<40
                assert crop.format=="PNG"
        checked=Image.open(BytesIO(base64.b64decode(list(symbols.values())[1]["data"])))
        assert any(b>r+80 for r,g,b in checked.convert("RGB").get_flattened_data())
        stream=StringIO()
        TemplateRenderer(stream).document("範本",[{"number":1,"symbols":symbols,"blocks":[
            {"kind":"paragraph","text":_lines(words)[0].text}]}])
        html=stream.getvalue()
        assert html.count('class="choice-image"')==3
        assert html.count('data-choice="page-1-choice-')==3
        assert "\ufff0" not in html and "<input" not in html
        assert 'checked=' not in html and 'data-checked' not in html


def test_choice_tokens_remain_visible_content_instead_of_field_labels_or_captions():
    token="\ufff01\ufff1"
    paragraphs=[{"kind":"paragraph","text":f"方式：{token}自行審閱"}]
    assert organize_prose(paragraphs,"p1")==paragraphs
    table=Table((0,100,200),(0,50),(Cell(0,0,1,1,Rect(0,0,100,50)),Cell(0,1,1,1,Rect(100,0,200,50))))
    model,_=table_model(table,[word(token,10,10),word("同意",110,10)],"t1")
    assert model["kind"]=="table" and token not in model["caption"]
    assert token in model["rows"][0]["cells"][0]["blocks"][0]["text"]


def test_repeated_name_mask_circles_are_not_choices():
    from PIL import ImageDraw
    with Image.new("RGB",(1000,300),"white") as image:
        drawing=ImageDraw.Draw(image)
        for left in (50,80):
            drawing.ellipse((left,50,left+20,70),outline="black",width=2)
        region=RecognizedRegion(word("王○○",20,48,81,24),words=(
            word("王",20,48,21,24),word("○",50,48,21,24),word("○",80,48,21,24)))
        words,symbols=preserve_choices(image,[region],1)
        assert not symbols and words==[region.line]


def test_real_template_ocr(request):
    if not request.config.getoption("--ocr-integration"):
        pytest.skip("Use --ocr-integration for a real OCR subprocess")
    from PIL import ImageDraw, ImageFont
    with Image.new("RGB",(800,300),"white") as image:
        font = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc",40) if Path("C:/Windows/Fonts/msjh.ttc").exists() else ImageFont.load_default(size=40)
        ImageDraw.Draw(image).text((30,40),"FORM 12345",fill="black",font=font)
        regions = TemplateOcr(OcrOptions(timeout=120)).recognize(image)
    assert "12345" in "".join(region.line.text for region in regions)


def test_browser_template_can_accept_a_new_table_row_and_wrap_text(tmp_path,request):
    channel = request.config.getoption("--browser-channel")
    if not channel:
        pytest.skip("Use --browser-channel for browser validation")
    from playwright.sync_api import sync_playwright
    page_path = tmp_path/"template.html"
    table = {"kind":"table","caption":"商品資料","header_rows":1,"rows":[
        {"cells":[{"role":"columnheader","blocks":[{"kind":"paragraph","text":"商品名稱"}]}]},
        {"cells":[{"role":"cell","blocks":[]}]}]}
    with page_path.open("w",encoding="utf-8") as stream:
        TemplateRenderer(stream).document("測試範本",[{"number":1,"blocks":[table,{"kind":"paragraph","text":"簽名：___"}]}])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel,headless=True)
        page = browser.new_page()
        requests,errors = [],[]
        page.on("request",lambda req: requests.append(req.url) if req.url.startswith(("http:","https:")) else None)
        page.on("pageerror",lambda error: errors.append(str(error)))
        page.goto(page_path.as_uri())
        before = page.locator("article > p").bounding_box()["y"]
        page.locator("tbody").evaluate("element => {const row=element.insertRow(); row.insertCell().textContent='新增商品內容'.repeat(200);}")
        assert page.locator("article > p").bounding_box()["y"] > before
        assert page.locator("tbody tr").count() == 2
        assert page.locator("input, textarea, script, svg").count() == 0
        page.pdf(path=str(tmp_path/"print.pdf"),prefer_css_page_size=True)
        assert not errors and not requests
        browser.close()
