"""Verify editing/persistence and compare foreground ink with the original.

Pixel similarity does not validate OCR text, numbers or checkbox meaning.
"""

import argparse
from contextlib import closing
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright
import pypdfium2 as pdfium


def compare(reference, actual):
    expected = np.asarray(reference.convert("L").resize(actual.size,Image.Resampling.LANCZOS))<170
    rendered = np.asarray(actual.convert("L"))<170
    kernel = np.ones((3,3),np.uint8)
    expected_near = cv2.dilate(expected.astype(np.uint8),kernel)>0
    rendered_near = cv2.dilate(rendered.astype(np.uint8),kernel)>0
    precision = float((rendered & expected_near).sum()/max(1,rendered.sum()))
    recall = float((expected & rendered_near).sum()/max(1,expected.sum()))
    difference = np.full((*expected.shape,3),255,np.uint8)
    difference[expected & ~rendered_near] = (220,40,40)
    difference[rendered & ~expected_near] = (30,90,220)
    return {"foreground_precision_tolerance_1px":round(precision,4),
            "foreground_recall_tolerance_1px":round(recall,4),
            "foreground_f1_tolerance_1px":round(2*precision*recall/max(.0001,precision+recall),4)}, Image.fromarray(difference)


def verify(source, output, directory, channel="msedge"):
    directory.mkdir(parents=True,exist_ok=True)
    report = {"source":source.name,"output":str(output),"pages":[],"network_requests":[],"errors":[]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel,headless=True)
        page = browser.new_page(viewport={"width":1300,"height":1300},device_scale_factor=1)
        page.on("request",lambda request: report["network_requests"].append(request.url) if request.url.startswith(("http:","https:")) else None)
        page.on("pageerror",lambda error: report["errors"].append(str(error)))
        page.goto(output.as_uri())
        page.wait_for_selector('html[data-layout-ready="true"]')
        with pdfium.PdfDocument(source) as document:
            assert page.locator(".page").count()==len(document)
            for index in range(len(document)):
                locator=page.locator(".page").nth(index)
                filename=directory/f"page-{index+1}.png"
                locator.screenshot(path=str(filename))
                with closing(document[index]) as pdf_page, closing(pdf_page.render(scale=2)) as bitmap:
                    with bitmap.to_pil() as reference, Image.open(filename) as rendered:
                        metrics,difference=compare(reference,rendered)
                        difference.save(directory/f"difference-{index+1}.png")
                metrics["editable_blocks"]=locator.locator(".editable-text").count()
                metrics["checkboxes"]=locator.locator(".check-box").count()
                metrics["image_fragments"]=locator.locator(".image-fragment").count()
                report["pages"].append(metrics)
        report["text_visible"]=page.locator(".editable-text").first.is_visible()
        editable=page.locator(".editable-text").first
        identifier=editable.locator("..").get_attribute("id")
        editable.fill("123456.78")
        checkbox=page.locator(".check-box").first
        checkbox_id=None
        if checkbox.count():
            checkbox_id=checkbox.get_attribute("id")
            checkbox.set_checked(not checkbox.is_checked())
            checked=checkbox.is_checked()
        with page.expect_download() as download:
            page.locator("#save-html").click()
        # Save next to the source HTML so the local relative asset links work.
        saved=output.with_name(output.stem+"-persistence-check.html")
        download.value.save_as(saved)
        try:
            page.goto(saved.as_uri())
            page.wait_for_selector('html[data-layout-ready="true"]')
            assert page.locator(f"#{identifier} .editable-text").inner_text()=="123456.78"
            if checkbox_id:
                assert page.locator(f"#{checkbox_id}").is_checked()==checked
            report["edit_save_reload"]=True
            page.locator("#show-source").check()
            assert page.locator(".source-reference").first.is_visible()
            assert page.locator(".editable-text").first.get_attribute("contenteditable")=="false"
            page.locator("#show-source").uncheck()
        finally:
            saved.unlink(missing_ok=True)
        page.goto(output.as_uri())
        page.wait_for_selector('html[data-layout-ready="true"]')
        page.pdf(path=str(directory/"printed.pdf"),prefer_css_page_size=True,print_background=True)
        with pdfium.PdfDocument(directory/"printed.pdf") as printed:
            report["printed_pages"]=len(printed)
        assert report["printed_pages"]==len(report["pages"]),"Printed page count differs from source"
        browser.close()
    assert not report["errors"],report["errors"]
    assert not report["network_requests"]
    (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("directory",type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.source,args.output,args.directory),ensure_ascii=False,indent=2))
