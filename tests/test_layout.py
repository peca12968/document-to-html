import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont
import pytest

pytest.importorskip("cv2",reason="Install .[layout] for layout reconstruction tests")

from document_to_html import ConversionOptions, OcrOptions, convert
from document_to_html.errors import ConversionError
from document_to_html.layout_analysis import (Primitive, detect_primitives, position_text,
                                             plausible_text_geometry)
from document_to_html.layout_ocr import LayoutOcr, RecognizedRegion, parse_regions
from document_to_html.ocr import OcrLine
from document_to_html.structure import Rect


def scan_fixture(path):
    with Image.new("RGB",(800,1000),"white") as image:
        draw=ImageDraw.Draw(image)
        draw.rectangle((70,150,730,200),fill="#e9e9e9")
        draw.line((70,150,730,150),fill="#999999",width=2)
        draw.rectangle((100,250,120,270),outline="black",width=2)
        draw.rectangle((180,250,200,270),outline="black",width=2)
        draw.line((184,258,189,265,197,252),fill="black",width=2)
        draw.text((75,80),"Editable 12345",fill="black",font_size=25)
        image.save(path,"PDF",resolution=100)
    return path


def test_checkbox_state_and_real_css_rules():
    with Image.new("RGB",(800,1000),"white") as image:
        draw=ImageDraw.Draw(image)
        draw.rectangle((100,250,120,270),outline="black",width=2)
        draw.rectangle((180,250,200,270),outline="black",width=2)
        draw.line((184,258,189,265,197,252),fill="black",width=2)
        draw.line((70,150,730,150),fill="#dddddd",width=2)
        _,rules,checkboxes,_=detect_primitives(image)
    ordered=sorted(checkboxes,key=lambda box:box.bounds.left)
    assert len(ordered)==2
    assert not ordered[0].checked and ordered[1].checked
    assert any(rule.bounds.width>=660 and rule.color=="#dddddd" for rule in rules)


def test_words_do_not_stretch_across_checkbox():
    import numpy as np
    with Image.new("RGB",(400,200),"white") as image:
        draw=ImageDraw.Draw(image)
        draw.rectangle((100,80,115,100),fill="black")
        draw.rectangle((170,80,185,100),fill="black")
        first=OcrLine("A",98,78,22,25,99)
        second=OcrLine("B",168,78,22,25,99)
        region=RecognizedRegion(OcrLine("AB",98,78,95,25,99),words=(first,second))
        words=position_text(region,image,np.zeros((200,400),np.uint8),
                            [Primitive("checkbox",Rect(135,80,155,100))])
    assert len(words)==2
    assert words[0].bounds.right<=120 and words[1].bounds.left>=168


def test_dashed_separator_is_css_rule_instead_of_many_image_fragments():
    with Image.new("RGB",(800,1000),"white") as image:
        draw=ImageDraw.Draw(image)
        for left in range(50,750,15):
            draw.line((left,200,left+8,200),fill="#aaaaaa",width=2)
        _,rules,_,_=detect_primitives(image)
    assert any(rule.metadata.get("pattern")=="dashed" and rule.bounds.width>600 for rule in rules)


def test_collapsed_ocr_is_not_stretched_across_a_long_paragraph():
    assert not plausible_text_geometry(Primitive("text",Rect(10,10,1650,44),text="。系系系（一）",confidence=60))
    assert plausible_text_geometry(Primitive("text",Rect(10,10,190,40),text="授信申請書",confidence=99))


@pytest.mark.parametrize("value",[
    {"text":"test","confidence":float("nan"),"box":[[0,0],[1,0],[1,1],[0,1]]},
    {"text":"test","confidence":99,"box":[[0,0],[float("inf"),0],[1,1],[0,1]]},
    {"text":"test","confidence":999,"box":[[0,0],[1,0],[1,1],[0,1]]},
])
def test_invalid_ocr_geometry_is_rejected(value):
    with pytest.raises(ValueError):
        parse_regions([value],100,100)


def test_layout_native_text_does_not_require_ocr_and_assets_are_readable(source_pdf,monkeypatch):
    def fail(*args):
        raise AssertionError("No OCR for a native text-only PDF")
    monkeypatch.setattr(LayoutOcr,"recognize",fail)
    result=convert(source_pdf,options=ConversionOptions(output_mode="layout",ocr=OcrOptions(dpi=100)))
    html=result.output.read_text(encoding="utf-8")
    assert ">Hello</span>" in html and ">HTML</span>" in html and ">1</span>" in html
    assert "base64," not in html
    assert "border-top:" in html and "editable-text" in html
    assert result.assets.is_dir() and not result.ocr_pages
    model=json.loads((result.assets/"document.json").read_text(encoding="utf-8"))
    assert len(model["pages"])==2
    assert model["coordinate_unit"]=="PDF point"
    assert model["pages"][0]["color_graphics"]==0  # blue page border is not a logo


def test_layout_failure_preserves_previous_output_and_removes_only_new_assets(tmp_path,monkeypatch):
    source=scan_fixture(tmp_path/"scan.pdf")
    output=tmp_path/"previous.html"
    output.write_text("previous",encoding="utf-8")
    previous_assets=tmp_path/"previous-assets-existing"
    previous_assets.mkdir()
    (previous_assets/"keep.txt").write_text("keep")
    def fail(*args):
        raise ConversionError("OCR timeout")
    monkeypatch.setattr(LayoutOcr,"recognize",fail)
    with pytest.raises(ConversionError,match="timeout"):
        convert(source,output,options=ConversionOptions(output_mode="layout",overwrite=True,ocr=OcrOptions(dpi=100)))
    assert output.read_text()=="previous"
    assert list(tmp_path.glob("previous-assets-*"))==[previous_assets]
    assert (previous_assets/"keep.txt").read_text()=="keep"
    assert not list(tmp_path.glob(".document-to-html-*.tmp"))


def test_asset_directory_collision_does_not_remove_existing_assets(source_pdf,monkeypatch):
    from types import SimpleNamespace
    existing=source_pdf.parent/"example-assets-123456789abc"
    existing.mkdir()
    (existing/"keep.txt").write_text("keep")
    monkeypatch.setattr("document_to_html.converter.uuid.uuid4",lambda:SimpleNamespace(hex="123456789abc"))
    with pytest.raises(ConversionError):
        convert(source_pdf,options=ConversionOptions(output_mode="layout"))
    assert (existing/"keep.txt").read_text()=="keep"


def test_layout_ocr_timeout_is_bounded(tmp_path,monkeypatch):
    def timeout(*args,**kwargs):
        assert kwargs["timeout"]==3
        raise subprocess.TimeoutExpired(args[0],3)
    monkeypatch.setattr("document_to_html.layout_ocr.subprocess.run",timeout)
    with Image.new("RGB",(100,100),"white") as image:
        with pytest.raises(ConversionError,match="時間上限"):
            LayoutOcr(OcrOptions(timeout=3)).recognize(image)


def test_scanned_html_escapes_ocr_text(tmp_path,monkeypatch):
    source=scan_fixture(tmp_path/"scan.pdf")
    monkeypatch.setattr(LayoutOcr,"recognize",lambda *_:(RecognizedRegion(OcrLine('<img src=x onerror=alert(1)>',75,80,180,30,99)),))
    result=convert(source,options=ConversionOptions(output_mode="layout",ocr=OcrOptions(dpi=100)))
    html=result.output.read_text(encoding="utf-8")
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img src=x" not in html


def test_saved_html_preserves_edits_and_checkbox_state_without_network(tmp_path,request,monkeypatch):
    channel=request.config.getoption("--browser-channel")
    if not channel:
        pytest.skip("Use --browser-channel for browser checks")
    source=scan_fixture(tmp_path/"scan.pdf")
    monkeypatch.setattr(LayoutOcr,"recognize",lambda *_:(RecognizedRegion(OcrLine("Editable 12345",75,80,180,30,99)),))
    result=convert(source,options=ConversionOptions(output_mode="layout",ocr=OcrOptions(dpi=100)))
    from scripts.verify_layout import verify
    report=verify(source,result.output,tmp_path/"browser",channel)
    assert report["edit_save_reload"]
    assert report["printed_pages"]==1
    assert not report["network_requests"] and not report["errors"]


def test_real_local_ocr_with_network_disabled(tmp_path,request):
    if not request.config.getoption("--ocr-integration"):
        pytest.skip("Use --ocr-integration for real engine checks")
    pytest.importorskip("rapidocr")
    # The normal worker provides explicit packaged model paths; patch its network
    # dependencies in a separate process to verify it never tries to download.
    source=tmp_path/"page.png"
    chinese_font=next((path for path in (
        Path("C:/Windows/Fonts/kaiu.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")) if path.is_file()),None)
    with Image.new("RGB",(800,300),"white") as image:
        ImageDraw.Draw(image).text((40,100),"Invoice 123456",fill="black",font_size=50)
        if chinese_font:
            ImageDraw.Draw(image).text((40,180),"授信申請書",fill="black",font=ImageFont.truetype(str(chinese_font),48))
        image.save(source)
    output=tmp_path/"result.json"
    import sys
    code=("import socket,sys; "
          "socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network forbidden')); "
          "from document_to_html.layout_worker import main; main()")
    subprocess.run([sys.executable,"-c",code,str(source),str(output)],check=True,capture_output=True,timeout=60)
    text="".join(value["text"] for value in json.loads(output.read_text(encoding="utf-8")))
    assert "123456" in text
    if chinese_font:
        assert "授信申請書" in text
