"""Generate a synthetic multi-page PDF and read original page numbers from both HTML outputs."""
from argparse import ArgumentParser
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from document_to_html import ConversionOptions, OcrOptions, convert
from scripts.synthetic_pdf import make_pdf


class PageMarkup(HTMLParser):
    def __init__(self, output):
        super().__init__()
        self.pages = []
        self.text = []
        self.feed(output.read_text(encoding="utf-8"))
        self.close()

    def handle_starttag(self, tag, raw):
        attrs = dict(raw)
        if tag in {"section", "article"} and "data-page" in attrs:
            self.pages.append({"number": int(attrs["data-page"]), "label": attrs["aria-label"]})

    def handle_data(self, data):
        if match := re.fullmatch(r"Hello HTML [0-9]+", data.strip()):
            self.text.append(match[0])


def generate(directory):
    source_pages = 4
    selection = "4,2"
    source = make_pdf(directory / "selection.pdf", pages=source_pages)
    report = {"source_pages": source_pages, "selection": selection}
    for mode in ("visual", "structured"):
        result = convert(source, directory / f"{mode}.html", options=ConversionOptions(
            dpi=96, output_mode=mode, pages=selection, ocr=OcrOptions(mode="off", dpi=96)))
        output = PageMarkup(result.output)
        pages = [{**markup, "text": text} for markup, text in zip(output.pages, output.text, strict=True)]
        if len(pages) != result.pages or [row["number"] for row in pages] != [2, 4]:
            raise ValueError("sample output lost the selected source pages")
        report[mode] = pages
    return report


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="new directory to keep the source PDF and HTML outputs")
    args = parser.parse_args()
    if args.directory is None:
        with TemporaryDirectory() as directory:
            report = generate(Path(directory))
    else:
        args.directory.mkdir()
        report = generate(args.directory)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
