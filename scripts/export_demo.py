"""Convert one synthetic form and extract a small, inert preview of both HTML modes."""

from argparse import ArgumentParser
from base64 import b64decode
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from document_to_html import ConversionOptions, OcrOptions, convert
from scripts.synthetic_pdf import make_pdf


FORM = b"""
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
"""
DPI = 96
PNG_PREFIX = "data:image/png;base64,"


class FormOutput(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.title = ""
        self.image = None
        self.lines = []
        self.tables = []
        self.table = self.row = self.capture = None
        self.feed(path.read_text(encoding="utf-8"))
        self.close()

    def handle_starttag(self, tag, raw):
        attrs = dict(raw)
        if tag == "img" and attrs.get("class") == "page-image":
            source = attrs["src"]
            if self.image is not None or not source.startswith(PNG_PREFIX):
                raise ValueError("expected one PNG page image")
            self.image = (source.removeprefix(PNG_PREFIX), int(attrs["width"]), int(attrs["height"]))
        elif tag == "table" and attrs.get("class") == "source-table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("title", "text") or (tag in ("th", "td") and self.row is not None):
            self.capture = tag, attrs, []

    def handle_data(self, data):
        if self.capture:
            self.capture[2].append(data)

    def handle_endtag(self, tag):
        if self.capture and self.capture[0] == tag:
            _, attrs, parts = self.capture
            text = " ".join("".join(parts).split())
            if tag == "title":
                self.title = text
            elif tag == "text":
                if text:
                    self.lines.append(text)
            else:
                self.row.append({"text": text, "header": tag == "th", "rowspan": int(attrs.get("rowspan", 1)),
                                 "colspan": int(attrs.get("colspan", 1))})
            self.capture = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def generate(directory):
    source = make_pdf(directory / "sample-form.pdf", pages=1, page_content=FORM)
    visual, structured = [convert(source, directory / f"{mode}.html", options=ConversionOptions(
        dpi=DPI, output_mode=mode, ocr=OcrOptions(mode="off"))) for mode in ("visual", "structured")]
    picture, template = FormOutput(visual.output), FormOutput(structured.output)
    if visual.pages != 1 or structured.pages != 1 or visual.ocr_pages or structured.ocr_pages:
        raise ValueError("expected a one-page native-text form in both modes")
    if picture.image is None or not picture.lines or not template.title or not template.tables:
        raise ValueError("the converted sample is missing its image, text or native form table")
    png, width, height = picture.image
    with Image.open(BytesIO(b64decode(png, validate=True))) as image:
        if image.format != "PNG" or image.size != (width, height):
            raise ValueError("page image does not match the visual HTML")
        image.verify()
    return {"source_sha256": sha256(source.read_bytes()).hexdigest(), "pages": visual.pages, "title": template.title,
            "visual": {"dpi": DPI, "width": width, "height": height, "png_base64": png, "text_lines": picture.lines},
            "structured": {"tables": template.tables}}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="new directory to keep the PDF and original HTML outputs")
    args = parser.parse_args()
    if args.directory is None:
        with TemporaryDirectory() as directory:
            fixture = generate(Path(directory))
    else:
        args.directory.mkdir()
        fixture = generate(args.directory)
    print(json.dumps(fixture, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
