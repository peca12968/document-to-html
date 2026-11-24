from base64 import b64decode
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from scripts.export_demo import generate


FIXTURE = Path(__file__).resolve().parents[1] / "examples/conversion-demo.json"


def test_both_native_pdf_outputs_recreate_the_preview(tmp_path):
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = generate(tmp_path)
    for key in ("title", "source_sha256", "pages", "structured"):
        assert actual[key] == expected[key]
    # PDFium can select different fallback glyphs on different operating systems.
    for key in ("dpi", "width", "height", "text_lines"):
        assert actual["visual"][key] == expected["visual"][key]
    assert "Signature" in expected["visual"]["text_lines"]
    assert [cell["text"] for cell in expected["structured"]["tables"][0][0]] == ["Name", "Example"]
    with Image.open(BytesIO(b64decode(expected["visual"]["png_base64"], validate=True))) as image:
        assert image.size == (320, 427)
        assert image.format == "PNG"
        image.verify()


def test_demo_outputs_are_searchable_and_structured_in_a_browser(tmp_path, request):
    channel = request.config.getoption("--browser-channel")
    if not channel:
        pytest.skip("Use --browser-channel chromium or msedge")
    from playwright.sync_api import sync_playwright

    report = generate(tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel=channel, headless=True)
        try:
            page = browser.new_page(viewport={"width": 360, "height": 800})
            external = []
            page.on("request", lambda request: external.append(request.url) if request.url.startswith(("http:", "https:")) else None)
            page.goto((tmp_path / "visual.html").as_uri())
            assert page.locator(".page-image").evaluate("image => image.decode().then(() => image.naturalWidth)") == 320
            assert page.evaluate("window.find('Signature')")
            page.goto((tmp_path / "structured.html").as_uri())
            table = page.get_by_role("table").and_(page.locator("table.source-table"))
            assert table.count() == len(report["structured"]["tables"])
            cells = table.first.get_by_role("row").first.get_by_role("cell").all_text_contents()
            assert [cell.strip() for cell in cells] == ["Name", "Example"]
            assert not external
        finally:
            browser.close()
