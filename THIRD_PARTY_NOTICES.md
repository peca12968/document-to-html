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
| OpenCV (optional template extra) | Detect table borders and graphic regions | Apache-2.0; [license](https://github.com/opencv/opencv/blob/4.x/LICENSE) |
| RapidOCR (optional template extra) | Local Chinese/English recognition | Apache-2.0; [project](https://github.com/RapidAI/RapidOCR) |
| PP-OCR ONNX models shipped in RapidOCR | Local text detection and recognition | Preserve the RapidOCR model notices and upstream PaddleOCR Apache-2.0 license |
| ONNX Runtime (optional template extra) | Execute local OCR models | MIT; [license](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) |

Development dependencies include pytest (MIT) and Playwright (Apache-2.0). The project does not bundle Microsoft Office, LibreOffice, proprietary fonts, or user documents. Font availability and permission to distribute document content remain the responsibility of the document owner.
