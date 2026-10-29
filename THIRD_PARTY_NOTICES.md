# Third-party components

This project uses the following independently licensed software. Installing or distributing dependencies must preserve their own license and notice files.

| Component | Purpose | License / reference |
| --- | --- | --- |
| pypdfium2 | Python PDFium bindings | Apache-2.0 / BSD-3-Clause; see the [project licensing documentation](https://github.com/pypdfium2-team/pypdfium2#licensing) |
| PDFium and bundled third-party libraries | PDF rendering and extraction | BSD-style and individual third-party licenses, shipped with pypdfium2 wheels |
| Pillow | Lossless PNG encoding | HPND; [license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| Tesseract (separately installed) | Offline OCR with word coordinates and confidence | Apache-2.0; [license](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE) |
| Tesseract traineddata (separately installed) | Traditional Chinese and English OCR models | See the chosen model repository; official [tessdata license](https://github.com/tesseract-ocr/tessdata/blob/main/LICENSE) |
| pywin32 (optional, Windows) | Microsoft Word COM automation | PSF-2.0; [license](https://github.com/mhammond/pywin32/blob/main/License.txt) |
| LibreOffice (separately installed) | Word to PDF conversion | MPL-2.0 and related licenses; [license information](https://www.libreoffice.org/about-us/licenses/) |
| Microsoft Word (separately installed) | Word to PDF conversion | Proprietary; requires an appropriately licensed local installation |

Development dependencies include pytest (MIT) and Playwright (Apache-2.0). The project does not bundle Microsoft Office, LibreOffice, proprietary fonts, or user documents. Font availability and permission to distribute document content remain the responsibility of the document owner.

## 結構化模式額外相依

- OpenCV / opencv-python-headless：Apache-2.0，請參閱 [OpenCV LICENSE](https://github.com/opencv/opencv/blob/5.x/LICENSE) 與安裝 wheel 內的第三方授權清單。
- NumPy：BSD-3-Clause，請參閱 [NumPy LICENSE](https://github.com/numpy/numpy/blob/main/LICENSE.txt)；隨 OpenCV 安裝。

## 版面重建模式額外相依

- RapidOCR 3.10.0：Apache-2.0；[專案](https://github.com/RapidAI/RapidOCR)。安裝 wheel 內含 `LICENSE` 及 `MODEL_LICENSES.md`，應保留其授權與模型來源說明。
- 隨 RapidOCR wheel 附帶的 PP-OCRv6 small det / rec 及 ch_ppocr_mobile_v2.0_cls 模型：依該版本 `MODEL_LICENSES.md`，源自 PaddleOCR / Baidu 模型、以 Apache-2.0 提供；上游權利人與 RapidOCR 程式作者不同。本專案未修改或將模型另存入 Git，轉換只載入已安裝模型。
- ONNX Runtime 1.31.1：MIT；[專案授權](https://github.com/microsoft/onnxruntime/blob/main/LICENSE)。
- RapidOCR 間接相依套件（例如 Shapely、PyClipper、PyYAML、OmegaConf）以各安裝套件隨附授權為準；重新散布完整環境時需保留這些檔案。
- 字型只使用轉換電腦與瀏覽器已安裝字型，不複製 Windows 字型至 HTML 或儲存庫。
