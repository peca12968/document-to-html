"""Browser integration check; reports contain metrics, never extracted document text."""

from __future__ import annotations

import argparse
import base64
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import re

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright
import pypdfium2 as pdfium


def verify(html: Path, directory: Path, channel: str) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    image_data = re.findall(r'data:image/png;base64,([^\"]+)', html.read_text(encoding="utf-8"))
    report = {"pages": len(image_data), "browser": channel, "page_checks": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=1)
        external_requests, errors = [], []
        page.on("request", lambda request: external_requests.append(request.url) if request.url.startswith(("http:", "https:")) else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(html.resolve().as_uri())
        page.locator(".page-image").evaluate_all("images => Promise.all(images.map(image => image.decode()))")
        assert page.locator(".page").count() == len(image_data)
        page.screenshot(path=str(directory / "desktop.png"), full_page=False)
        # Verify transparent text is actually selectable and searchable by Chromium.
        selectable_characters = page.locator(".text-layer").evaluate_all(
            "layers => layers.map(layer => layer.textContent).join('').replace(/\\s/g, '').length")
        report["selectable_characters"] = selectable_characters
        if selectable_characters:
            text_probe = page.locator(".text-layer").first.evaluate("layer => layer.textContent.trim().slice(0, 4)")
            report["browser_find"] = page.evaluate("text => window.find(text)", text_probe)
            assert report["browser_find"], "Browser cannot find extracted text"
            page.evaluate("window.getSelection().removeAllRanges()")
        for index, data in enumerate(image_data):
            with Image.open(BytesIO(base64.b64decode(data))) as reference:
                page.set_viewport_size({"width": reference.width + 48, "height": reference.height + 200})
                section = page.locator(".page").nth(index)
                section.evaluate("(element, width) => { element.style.width = width + 'px'; element.style.maxWidth = 'none'; element.style.aspectRatio = 'auto'; element.style.boxShadow = 'none'; }", reference.width)
                section.locator("img").evaluate("image => image.style.height = 'auto'")
                screenshot = section.screenshot()
                with Image.open(BytesIO(screenshot)) as actual:
                    assert actual.size == reference.size, (actual.size, reference.size)
                    difference = ImageChops.difference(actual.convert("RGB"), reference.convert("RGB"))
                    mean_error = sum(ImageStat.Stat(difference).mean) / 3
                    report["page_checks"].append({"page": index + 1, "mean_absolute_pixel_error": mean_error})
                    assert mean_error < 0.01, f"Page {index + 1}: visible layout differs from source image"
        # Reload to remove inspection-only styles before print and mobile checks.
        page.reload()
        page.locator(".page-image").evaluate_all("images => Promise.all(images.map(image => image.decode()))")
        printed = directory / "browser-print.pdf"
        page.pdf(path=str(printed), prefer_css_page_size=True, print_background=True, display_header_footer=False)
        with pdfium.PdfDocument(printed) as document:
            report["printed_pages"] = len(document)
            report["printed_page_sizes_pt"] = []
            for index in range(len(document)):
                with closing(document[index]) as pdf_page:
                    report["printed_page_sizes_pt"].append(pdf_page.get_size())
            assert len(document) == len(image_data), "Browser inserted extra pages"
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(directory / "mobile.png"))
        report["mobile_no_horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert report["mobile_no_horizontal_overflow"]
        assert not external_requests, "HTML unexpectedly requested network resources"
        assert not errors, "Browser JavaScript errors"
        report["external_requests"] = len(external_requests)
        report["page_errors"] = len(errors)
        browser.close()
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--channel", default="msedge")
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.html, arguments.output, arguments.channel), indent=2))
