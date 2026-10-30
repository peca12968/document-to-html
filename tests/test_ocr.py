import base64
from dataclasses import replace
from contextlib import closing
from io import BytesIO
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFont
import pypdfium2 as pdfium
import pytest

from document_to_html import ConversionOptions, OcrOptions, convert
from document_to_html.errors import ConversionError
from document_to_html.ocr import OcrLine, TesseractEngine, parse_tsv
from conftest import make_pdf


HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def raster_pdf(path, chinese=False):
    with Image.new("RGB", (1400, 800), "white") as image:
        draw = ImageDraw.Draw(image)
        if chinese:
            candidates = [Path("C:/Windows/Fonts/msjh.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
            font_path = next((path for path in candidates if path.is_file()), None)
            if font_path is None:
                pytest.skip("Traditional Chinese test font is not installed")
            font = ImageFont.truetype(str(font_path), 72)
            draw.text((80, 100), "申購申請書", font=font, fill="black")
            draw.text((80, 250), "申請人姓名", font=font, fill="black")
        else:
            draw.text((80, 100), "SCANNED DOCUMENT", font=ImageFont.load_default(size=65), fill="black")
            draw.text((80, 260), "Account number 123456", font=ImageFont.load_default(size=55), fill="black")
        image.save(path, "PDF", resolution=150)
    return path


def test_tsv_chinese_join_bounds_confidence_and_literal_text():
    data = HEADER + (
        "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t95\t申購\n"
        "5\t1\t1\t1\t1\t2\t40\t20\t50\t40\t50\t申請書\n"
        "5\t1\t1\t1\t2\t1\t-5\t80\t50\t30\t90\t<script>\n"
        "5\t1\t1\t1\t3\t1\t500\t20\t30\t40\t90\toutside\n"
        "5\t1\t1\t1\t4\t1\t10\t20\t30\t40\tnan\tinvalid\n"
    )
    lines = parse_tsv(data, 100, 100, 0)
    assert replace(lines[0], words=()) == OcrLine("申購申請書", 10, 20, 80, 40, 50)
    assert replace(lines[1], words=()) == OcrLine("<script>", 0, 80, 45, 20, 90)
    assert [(word.text, word.left, word.width) for word in lines[0].words] == [("申購", 10, 30), ("申請書", 40, 50)]
    assert len(lines) == 2
    assert parse_tsv(data, 100, 100, 60)[0].text == "申購"


def test_invalid_tsv_is_reported():
    with pytest.raises(ConversionError, match="TSV"):
        parse_tsv("bad header", 100, 100, 0)
    with pytest.raises(ConversionError, match="座標"):
        parse_tsv(HEADER + "5\t1\t1\t1\t1\t1\tbad\t1\t2\t2\t90\t文字\n", 100, 100, 0)


@pytest.mark.parametrize("options", [OcrOptions(mode="bad"), OcrOptions(language="../model"),
    OcrOptions(timeout=0), OcrOptions(psm=0), OcrOptions(dpi=601), OcrOptions(min_confidence=float("nan"))])
def test_invalid_ocr_options(options):
    with pytest.raises(ConversionError):
        options.validate()


def test_auto_scan_overlay_escapes_text_and_preserves_pixels(tmp_path, monkeypatch):
    source = raster_pdf(tmp_path / "scan.pdf")
    monkeypatch.setattr(TesseractEngine, "recognize", lambda self, image: (
        OcrLine("申購申請書<script>", 20, 30, 220, 60, 42),))
    result = convert(source)
    assert result.ocr_pages == (1,)
    assert any("信心分數" in warning for warning in result.warnings)
    html = result.output.read_text(encoding="utf-8")
    assert "申購申請書&lt;script&gt;" in html
    assert '<script>' not in html
    data = re.search(r'data:image/png;base64,([^\"]+)', html).group(1)
    with pdfium.PdfDocument(source) as document:
        document.init_forms()
        with closing(document[0]) as page, closing(page.render(scale=200 / 72)) as bitmap:
            with bitmap.to_pil() as expected, Image.open(BytesIO(base64.b64decode(data))) as actual:
                assert ImageChops.difference(expected.convert("RGB"), actual.convert("RGB")).getbbox() is None


def test_native_text_skips_ocr_and_always_replaces_it(source_pdf, monkeypatch):
    calls = []
    def recognize(self, image):
        calls.append(image.size)
        return (OcrLine("Replacement", 5, 5, 200, 40, 99),)
    monkeypatch.setattr(TesseractEngine, "recognize", recognize)
    native = convert(source_pdf)
    assert not calls and native.ocr_pages == ()
    forced = convert(source_pdf, source_pdf.parent / "forced.html", options=ConversionOptions(ocr=OcrOptions(mode="always")))
    assert forced.ocr_pages == (1, 2)
    assert len(calls) == 2
    html = forced.output.read_text(encoding="utf-8")
    assert "Replacement" in html and "Hello HTML" not in html


def test_no_text_layer_and_off_do_not_start_ocr(tmp_path, monkeypatch):
    source = raster_pdf(tmp_path / "scan.pdf")
    def unexpected(*args):
        raise AssertionError("OCR should not run")
    monkeypatch.setattr(TesseractEngine, "recognize", unexpected)
    for index, options in enumerate((ConversionOptions(text_layer=False), ConversionOptions(ocr=OcrOptions(mode="off")))):
        result = convert(source, tmp_path / f"off-{index}.html", options=options)
        assert not result.ocr_pages


def test_mixed_page_masks_native_text_but_retains_image_region(tmp_path, monkeypatch, request):
    source = make_pdf(tmp_path / "native.pdf", pages=1)
    mixed = tmp_path / "mixed.pdf"
    with pdfium.PdfDocument(source) as document:
        with closing(document[0]) as page, Image.new("RGB", (200, 80), "black") as image:
            with closing(pdfium.PdfBitmap.from_pil(image)) as bitmap:
                obj = pdfium.PdfImage.new(document)
                obj.set_bitmap(bitmap)
                obj.set_matrix(pdfium.PdfMatrix(200, 0, 0, 80, 20, 30))
                page.insert_obj(obj)
                page.gen_content()
                document.save(mixed)
    def recognize(self, image):
        # PDF native title at (30,250); OCR bitmap origin is top-left.
        with image.crop((120, 210, 700, 300)) as title_region:
            assert title_region.getextrema() == ((255, 255), (255, 255), (255, 255))
        assert image.getpixel((250, 1000)) == (0, 0, 0)
        return (OcrLine("圖片中文字", 50, 900, 300, 60, 90),)
    monkeypatch.setattr(TesseractEngine, "recognize", recognize)
    result = convert(mixed)
    html = result.output.read_text(encoding="utf-8")
    assert result.ocr_pages == (1,)
    assert "Hello HTML 1" in html and "圖片中文字" in html
    channel = request.config.getoption("--browser-channel")
    if channel:
        from scripts.verify_html import verify
        report = verify(result.output, tmp_path / "mixed-browser", channel)
        assert report["searchable_layers_checked"] == 2


def test_ocr_failure_preserves_existing_output_and_cleans_temporary_files(tmp_path, monkeypatch):
    source = raster_pdf(tmp_path / "scan.pdf")
    output = tmp_path / "keep.html"
    output.write_text("keep")
    def fail(*args):
        raise ConversionError("OCR 逾時")
    monkeypatch.setattr(TesseractEngine, "recognize", fail)
    with pytest.raises(ConversionError, match="逾時"):
        convert(source, output, options=ConversionOptions(overwrite=True))
    assert output.read_text() == "keep"
    assert not list(tmp_path.glob(".document-to-html-*.tmp"))


def test_missing_models_timeout_and_argument_safety(monkeypatch):
    import document_to_html.ocr as module
    monkeypatch.setattr(module, "find_tesseract", lambda path: "tesseract")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, b"eng\n", b""))
    with Image.new("RGB", (10, 10)) as image:
        with pytest.raises(ConversionError, match="chi_tra"):
            TesseractEngine(OcrOptions()).recognize(image)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ConversionError, match="逾時"):
        TesseractEngine(OcrOptions())._prepare()


def test_missing_executable_and_ocr_pixel_limit(tmp_path):
    source = make_pdf(tmp_path / "blank.pdf", text=False, pages=1)
    with pytest.raises(ConversionError, match="執行檔不存在"):
        convert(source, options=ConversionOptions(ocr=OcrOptions(executable=str(tmp_path / "not-installed.exe"))))
    with pytest.raises(ConversionError, match="OCR 頁面影像"):
        convert(source, options=ConversionOptions(dpi=72, max_pixels=100_000))
    assert not source.with_suffix(".html").exists()


def test_tesseract_uses_argument_list_and_cleans_private_png(monkeypatch):
    import document_to_html.ocr as module
    monkeypatch.setattr(module, "find_tesseract", lambda path: "tesseract")
    paths = []
    def run(command, **kwargs):
        assert isinstance(command, list) and not kwargs.get("shell", False)
        if "--list-langs" in command:
            return subprocess.CompletedProcess(command, 0, b"chi_tra\neng\n", b"")
        source = Path(command[1])
        assert source.exists()
        paths.append(source)
        assert command[2] == "stdout"
        assert command[command.index("-l") + 1] == "chi_tra+eng"
        return subprocess.CompletedProcess(command, 0, HEADER.encode(), b"")
    monkeypatch.setattr(subprocess, "run", run)
    with Image.new("RGB", (10, 10)) as image:
        assert TesseractEngine(OcrOptions()).recognize(image) == ()
    assert paths and not paths[0].parent.exists()


@pytest.mark.parametrize("chinese", [False, True])
def test_real_tesseract_scan(tmp_path, request, chinese):
    if not request.config.getoption("--ocr-integration"):
        pytest.skip("Use --ocr-integration with installed Tesseract models")
    source = raster_pdf(tmp_path / "ocr-real.pdf", chinese=chinese)
    result = convert(source, options=ConversionOptions(ocr=OcrOptions(language="chi_tra+eng" if chinese else "eng", psm=6)))
    html = result.output.read_text(encoding="utf-8")
    assert result.ocr_pages == (1,)
    assert ("申購申請書" if chinese else "SCANNED DOCUMENT") in html
    channel = request.config.getoption("--browser-channel")
    if channel:
        from scripts.verify_html import verify
        report = verify(result.output, tmp_path / "browser", channel)
        assert report["browser_find"]
