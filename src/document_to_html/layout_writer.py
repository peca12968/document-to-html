"""Fixed-page editable HTML backed by inspectable geometry and local assets."""

from contextlib import closing
from dataclasses import asdict
from html import escape
import json
import math
from pathlib import Path
import shutil
from urllib.parse import quote

from PIL import ImageDraw
import pypdfium2 as pdfium

from .errors import ConversionError
from .layout_analysis import (Primitive, detect_primitives, preserve_residuals,
                              preserve_color_graphics, select_font, position_text, assign_font_weight,
                              plausible_text_geometry)
from .layout_ocr import LayoutOcr, RecognizedRegion
from .ocr import OcrOptions
from .ocr_layer import needs_ocr
from .structure import detect_structure
from .structured_writer import _native_words


def _geometry(bounds, scale):
    return f"left:{bounds.left*scale:.4f}pt;top:{bounds.top*scale:.4f}pt;width:{bounds.width*scale:.4f}pt;height:{bounds.height*scale:.4f}pt;"


def _write_primitive(stream, item, identifier, scale, assets_url):
    geometry = _geometry(item.bounds, scale)
    common = f'id="{identifier}" data-kind="{item.kind}" data-region="{item.group}"'
    if item.kind == "text":
        stream.write(f'      <div {common} class="text-box" data-confidence="{item.confidence:.2f}" '
                     f'data-original-text="{escape(item.text, quote=True)}" '
                     f'style="{geometry}color:{item.color};font-family:\'{escape(item.font,quote=True)}\',serif;'
                     f'font-weight:{item.metadata.get("font_weight",400)};">'
                     f'<span class="editable-text" contenteditable="plaintext-only" role="textbox" '
                     f'aria-label="文字 {identifier}" spellcheck="false">{escape(item.text)}</span></div>\n')
    elif item.kind == "checkbox":
        stream.write(f'      <input {common} class="check-box" type="checkbox" '
                     f'aria-label="勾選框 {identifier}（請核對辨識狀態）" '
                     f'data-original-checked="{str(item.checked).lower()}" '
                     f'style="{geometry}color:{item.color};"{" checked" if item.checked else ""}>\n')
    elif item.kind == "image":
        stream.write(f'      <img {common} class="image-fragment" alt="未結構化的原稿圖形" '
                     f'title="保留原稿像素；此區域尚未轉成可編輯文字或圖形" '
                     f'src="{assets_url}/{item.asset}" style="{geometry}">\n')
    else:
        if item.kind == "rule":
            direction = item.metadata["orientation"]
            border = "border-top" if direction == "horizontal" else "border-left"
            thickness = (item.bounds.height if direction == "horizontal" else item.bounds.width)*scale
            pattern = item.metadata.get("pattern","solid")
            appearance = f"{border}:{thickness:.4f}pt {pattern} {item.color};"
        else:
            appearance = f"background-color:{item.color};"
        stream.write(f'      <div {common} class="{item.kind}" aria-hidden="true" style="{geometry}{appearance}"></div>\n')


def write_layout_html(pdf_path, stream, *, title, dpi, text_layer, password,
                      max_pages, max_pixels, progress, assets_directory, assets_name, ocr=None):
    ocr = ocr or OcrOptions()
    assets_directory = Path(assets_directory)
    assets_url = quote(assets_name, safe="")
    resources = Path(__file__).with_name("resources")
    for filename in ("layout.css", "layout.js"):
        shutil.copyfile(resources/filename, assets_directory/filename)
    engine = LayoutOcr(ocr)
    warnings = []
    pages_report = []
    ocr_pages = []
    characters = 0
    try:
        document = pdfium.PdfDocument(pdf_path,password=password)
    except pdfium.PdfiumError as error:
        raise ConversionError("PDF 無法開啟：檔案可能損毀或需要正確密碼。") from error
    with document:
        if not 0 < len(document) <= max_pages:
            raise ConversionError(f"PDF 頁數必須介於 1 與 {max_pages} 頁之間。")
        document.init_forms()
        stream.write('<!doctype html>\n<html lang="zh-Hant">\n<head>\n  <meta charset="utf-8">\n'
                     '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
                     '  <meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                     'script-src \'self\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\'; '
                     'connect-src \'none\'; base-uri \'none\'; form-action \'none\'">\n'
                     f'  <title>{escape(title)} — 版面重建</title>\n'
                     f'  <link rel="stylesheet" href="{assets_url}/layout.css">\n'
                     f'  <script src="{assets_url}/layout.js" defer></script>\n</head>\n<body>\n'
                     f'<header><h1>{escape(title)} — 版面重建</h1>\n'
                     '  <p>點選文字或勾選框即可修改。儲存的 HTML 需與原 assets 資料夾放在一起。</p>\n'
                     '  <nav><button id="save-html" type="button">儲存修改後 HTML</button> '
                     '<button id="save-data" type="button">匯出欄位 JSON</button> '
                     '<label><input id="show-source" type="checkbox">顯示原稿比對（暫停編輯）</label> '
                     '<label><input id="show-review" type="checkbox">標示待核對區域</label></nav>\n'
                     '  <p id="edit-status" role="status">OCR 文字與勾選狀態請核對；圖形保留為獨立圖片。</p>\n'
                     '</header>\n<main>\n')
        for index in range(len(document)):
            number = index+1
            with closing(document[index]) as page:
                page_width,page_height = page.get_size()
                scale = ocr.dpi/72
                if (not math.isfinite(page_width*page_height) or min(page_width,page_height)<=0
                        or math.ceil(page_width*scale)*math.ceil(page_height*scale)>max_pixels):
                    raise ConversionError(f"第 {number} 頁超過影像尺寸上限，請降低 --ocr-dpi。")
                with closing(page.render(scale=scale,fill_color=(255,255,255,255))) as bitmap:
                    with bitmap.to_pil().convert("RGB") as image:
                        fills,rules,checkboxes,mask = detect_primitives(image)
                        graphics = preserve_color_graphics(image,checkboxes,assets_directory,number)
                        native = _native_words(page,bitmap)
                        recognized = [] if ocr.mode=="always" else [RecognizedRegion(line) for line in native]
                        with image.copy() as recognition_image:
                            draw = ImageDraw.Draw(recognition_image)
                            for item in checkboxes+graphics:
                                b = item.bounds
                                draw.rectangle((b.left-2,b.top-2,b.right+2,b.bottom+2),fill="white")
                            if needs_ocr(page,len(native),ocr.mode):
                                draw = ImageDraw.Draw(recognition_image)
                                for region in recognized:
                                    b = region.line
                                    draw.rectangle((b.left-2,b.top-2,b.left+b.width+2,b.top+b.height+2),fill="white")
                                recognized.extend(engine.recognize(recognition_image))
                                ocr_pages.append(number)
                            texts = []
                            rotated_count = 0
                            for region in recognized:
                            # Axis-aligned reconstruction cannot faithfully rotate a
                            # paragraph; retain those pixels and report the limitation.
                                if abs(region.angle)>5:
                                    rotated_count += 1
                                    continue
                                # Native text was whitened only for mixed-page OCR;
                                # use source pixels for native ink bounds.
                                texts.extend(position_text(region,image if region.line in native else recognition_image,mask,checkboxes))
                        rejected_text = [item for item in texts if not plausible_text_geometry(item)]
                        texts = [item for item in texts if plausible_text_geometry(item)]
                        font = select_font(texts,image)
                        assign_font_weight(texts,image,font)
                        structure = detect_structure(image)
                        structure.cleaned.close()
                        for item in texts:
                            item.font = font
                            center = ((item.bounds.left+item.bounds.right)/2,(item.bounds.top+item.bounds.bottom)/2)
                            for table_index,table in enumerate(structure.tables,1):
                                owner = next((cell for cell in table.cells if cell.bounds.contains(*center)),None)
                                if owner:
                                    item.group = f"p{number}-table-{table_index}-r{owner.row+1}-c{owner.column+1}"
                                    item.metadata.update({"row":owner.row+1,"column":owner.column+1,
                                                          "rowspan":owner.rowspan,"colspan":owner.colspan})
                                    break
                        primitives = fills+rules+graphics+checkboxes+texts
                        fragments,remaining = preserve_residuals(image,primitives,mask,assets_directory,number)
                        # Reference image is only shown by the explicit comparison
                        # switch. It is never the reconstructed page background.
                        image.save(assets_directory/f"page-{number}-source.png")
                        primitives = fills+rules+graphics+fragments+checkboxes+texts
                        low = sum(item.confidence<85 for item in texts)
                        report = {"page":number,"width_pt":page_width,"height_pt":page_height,
                                  "analysis_dpi":ocr.dpi,"font_candidate":font,
                                  "text_blocks":len(texts),"low_confidence_blocks":low,
                                  "checkboxes":len(checkboxes),"rules":len(rules),
                                  "image_fragments":len(fragments),"residual_ink_ratio":remaining,
                                  "color_graphics":len(graphics),
                                  "rotated_regions_kept_as_images":rotated_count,
                                  "implausible_text_regions_kept_as_images":len(rejected_text),
                                  "quality_status":"needs-review","elements":[]}
                        characters += sum(len(item.text) for item in texts)
                        stream.write(f'  <style>@page sheet{number} {{size:{page_width:.4f}pt {page_height:.4f}pt;margin:0}}</style>\n'
                                     f'  <section class="page" data-page="{number}" aria-label="第 {number} 頁" '
                                     f'style="width:{page_width:.4f}pt;height:{page_height:.4f}pt;page:sheet{number}">\n'
                                     '    <!-- CSS 底色與線條、獨立圖形、可編輯文字；座標單位為 PDF point。 -->\n')
                        for position,item in enumerate(primitives,1):
                            identifier = f"p{number}-{item.kind}-{position:04d}"
                            _write_primitive(stream,item,identifier,1/scale,assets_url)
                            data = asdict(item)
                            data["id"] = identifier
                            b = item.bounds
                            data["bounds_pt"] = {"left":b.left/scale,"top":b.top/scale,
                                                  "width":b.width/scale,"height":b.height/scale}
                            report["elements"].append(data)
                        stream.write(f'    <img class="source-reference" src="{assets_url}/page-{number}-source.png" '
                                     'alt="原始 PDF，比對模式限定" hidden>\n  </section>\n')
                        pages_report.append(report)
                        warnings.append(f"第 {number} 頁：{len(texts)} 個文字區塊、{len(checkboxes)} 個勾選框、"
                                        f"{low} 個低信心區塊、{len(fragments)} 個未結構化圖片片段，"
                                        f"{len(rejected_text)} 個文字幾何衝突改留圖片，需核對。")
            if progress:
                progress(number,len(document))
        stream.write('</main>\n</body>\n</html>\n')
        data = {"schema_version":1,"title":title,"mode":"layout","coordinate_unit":"PDF point",
                "notes":["版面位置保留；業務欄位意義尚未自動確認。",
                          "residual_ink_ratio 是殘留圖片片段的暗像素比例（不含另存的彩色圖形），不是 OCR 準確率或還原分數。",
                          "模型不明確的文字也可能有高信心分數；勾選框及數值均需核對。"],
                "pages":pages_report}
        (assets_directory/"document.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        return len(document),characters,tuple(warnings),tuple(ocr_pages)
