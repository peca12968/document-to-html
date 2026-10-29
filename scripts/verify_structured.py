"""Browser smoke checks for reconstructed HTML (not a pixel-fidelity claim)."""

import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright


def verify(source: Path, output: Path, channel="msedge"):
    output.mkdir(parents=True, exist_ok=True)
    requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({"channel": channel} if channel != "chromium" else {}))
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 1400})
            page.on("request", lambda request: requests.append(request.url)
                    if request.url.startswith(("http://", "https://")) else None)
            page.goto(source.resolve().as_uri())
            assert page.locator("img,svg,script,iframe").count() == 0
            pages = page.locator(".page")
            count = pages.count()
            overflows = pages.evaluate_all("elements => elements.map(p => Math.max(0,p.scrollHeight-p.clientHeight))")
            for index in range(count):
                pages.nth(index).screenshot(path=str(output / f"page-{index+1}.png"))
            editable = page.locator('[contenteditable="plaintext-only"]').first
            editable.fill("123456.78")
            assert editable.inner_text() == "123456.78"
            # Only in-memory editing is promised. Reload must restore source.
            page.reload()
            assert page.locator('[contenteditable="plaintext-only"]').first.inner_text() != "123456.78"
            printed = output / "print.pdf"
            page.pdf(path=str(printed), prefer_css_page_size=True, print_background=True)
            with pdfium.PdfDocument(printed) as document:
                print_pages = len(document)
            report = {"pages": count, "tables": page.locator("table").count(),
                      "cells": page.locator("td").count(), "rules": page.locator(".rule").count(),
                      "editable": True, "network_requests": len(requests),
                      "vertical_overflow_pixels": overflows, "print_pages": print_pages}
            assert not requests
            assert print_pages == count, report
            assert all(value <= 2 for value in overflows), report
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            return report
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--channel", default="msedge")
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.source, arguments.output, arguments.channel), indent=2))
