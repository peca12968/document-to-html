from __future__ import annotations

import argparse
import getpass
import sys

from .converter import ConversionOptions, convert
from .errors import ConversionError
from .ocr import OcrOptions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="將 Word / PDF 轉為單一離線高還原 HTML。")
    parser.add_argument("source", nargs="?", help=".pdf / .doc / .docx 檔案")
    parser.add_argument("-o", "--output", help="HTML 輸出路徑（預設與來源同名）")
    parser.add_argument("--dpi", type=int, default=200, help="影像解析度 72–600，預設 200")
    parser.add_argument("--backend", choices=["auto", "word", "libreoffice"], default="auto")
    parser.add_argument("--libreoffice", help="LibreOffice 執行檔路徑")
    parser.add_argument("--timeout", type=int, default=120, help="Word 引擎逾時秒數")
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--no-text-layer", action="store_true", help="只保留頁面影像")
    parser.add_argument("--ocr", choices=["auto", "always", "off"], default="auto", help="預設自動辨識掃描頁與混合圖片頁")
    parser.add_argument("--ocr-language", default="chi_tra+eng", help="Tesseract 語言模型")
    parser.add_argument("--ocr-dpi", type=int, default=300)
    parser.add_argument("--ocr-timeout", type=int, default=120, help="每頁 OCR 逾時秒數")
    parser.add_argument("--ocr-psm", type=int, default=3, help="3 自動排版；11 稀疏文字；5 直排區塊")
    parser.add_argument("--ocr-min-confidence", type=float, default=0)
    parser.add_argument("--tesseract", help="Tesseract 執行檔路徑")
    parser.add_argument("--tessdata", help="Tesseract 語言模型資料夾")
    parser.add_argument("--ask-password", action="store_true", help="以隱藏輸入讀取 PDF 密碼")
    parser.add_argument("--overwrite", action="store_true", help="允許覆蓋指定 HTML")
    parser.add_argument("--gui", action="store_true", help="開啟桌面介面")
    arguments = parser.parse_args(argv)
    if arguments.gui:
        from .gui import main as gui_main
        gui_main()
        return 0
    if not arguments.source:
        parser.error("請指定來源檔案，或使用 --gui。")
    try:
        password = getpass.getpass("PDF 密碼：") if arguments.ask_password else None
        result = convert(
            arguments.source, arguments.output, password=password,
            options=ConversionOptions(
                dpi=arguments.dpi, backend=arguments.backend, libreoffice=arguments.libreoffice,
                timeout=arguments.timeout, max_pages=arguments.max_pages,
                text_layer=not arguments.no_text_layer, overwrite=arguments.overwrite,
                ocr=OcrOptions(mode=arguments.ocr, language=arguments.ocr_language,
                               dpi=arguments.ocr_dpi, timeout=arguments.ocr_timeout,
                               psm=arguments.ocr_psm, min_confidence=arguments.ocr_min_confidence,
                               executable=arguments.tesseract, tessdata=arguments.tessdata),
            ),
            progress=lambda current, total: print(f"轉換中：{current}/{total}", file=sys.stderr),
        )
    except (ConversionError, EOFError) as error:
        print(f"錯誤：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消轉換。", file=sys.stderr)
        return 130
    print(f"完成：{result.output}\n頁數：{result.pages}；引擎：{result.backend}")
    if result.ocr_pages:
        print(f"已執行 OCR 頁數：{len(result.ocr_pages)}；辨識內容請核對原始影像。")
    for warning in result.warnings:
        print(f"提醒：{warning}", file=sys.stderr)
    return 0
