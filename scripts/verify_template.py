"""Validate a local static template in a real browser; do not report OCR accuracy."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
import pypdfium2 as pdfium


def verify(html, directory, channel="msedge"):
    directory.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width":1100, "height":1100})
        requests, errors = [], []
        page.on("request", lambda request: requests.append(request.url)
                if request.url.startswith(("http:", "https:")) else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(html.resolve().as_uri())
        page.locator("img").evaluate_all("images => Promise.all(images.map(image => image.decode()))")
        report = {"tables":page.locator("table").count(), "sections":page.locator("section").count(),
                  "static_fields":page.locator("[data-label]").count(), "images":page.locator("img").count(),
                  "graphics":page.locator("figure img").count(), "choice_images":page.locator(".choice-image").count(),
                  "editable_controls":page.locator("input,textarea,select,[contenteditable]").count(),
                  "external_requests":len(requests), "page_errors":len(errors)}
        assert not report["editable_controls"]
        assert "\ufff0" not in page.locator("body").inner_text()
        assert page.locator("[data-choice]").count() == report["choice_images"]
        assert page.locator("script,svg,canvas,iframe").count() == 0
        assert page.locator("img").evaluate_all("images => images.every(image => image.src.startsWith('data:image/png;base64,'))")
        assert page.locator("main *").evaluate_all("elements => elements.every(element => !['absolute','fixed'].includes(getComputedStyle(element).position))")
        page.screenshot(path=str(directory/"desktop.png"), full_page=True)
        printed = directory/"printed.pdf"
        page.pdf(path=str(printed), prefer_css_page_size=True, print_background=True)
        with pdfium.PdfDocument(printed) as document:
            report["printed_pages"] = len(document)
            assert len(document) > 0
        page.set_viewport_size({"width":390,"height":844})
        report["mobile_horizontal_overflow_px"] = page.evaluate("Math.max(0,document.documentElement.scrollWidth-innerWidth)")
        page.screenshot(path=str(directory/"mobile.png"))
        assert not requests and not errors
        browser.close()
    (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("html",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--channel",default="msedge")
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.html,arguments.output,arguments.channel),ensure_ascii=False,indent=2))
