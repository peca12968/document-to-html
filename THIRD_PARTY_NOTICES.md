# Third-party components

This project uses the following independently licensed software. Installing or distributing dependencies must preserve their own license and notice files.

| Component | Purpose | License / reference |
| --- | --- | --- |
| pypdfium2 | Python PDFium bindings | Apache-2.0 / BSD-3-Clause; see the [project licensing documentation](https://github.com/pypdfium2-team/pypdfium2#licensing) |
| PDFium and bundled third-party libraries | PDF rendering and extraction | BSD-style and individual third-party licenses, shipped with pypdfium2 wheels |
| Pillow | Lossless PNG encoding | HPND; [license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| pywin32 (optional, Windows) | Microsoft Word COM automation | PSF-2.0; [license](https://github.com/mhammond/pywin32/blob/main/License.txt) |
| LibreOffice (separately installed) | Word to PDF conversion | MPL-2.0 and related licenses; [license information](https://www.libreoffice.org/about-us/licenses/) |
| Microsoft Word (separately installed) | Word to PDF conversion | Proprietary; requires an appropriately licensed local installation |

Development dependencies include pytest (MIT) and Playwright (Apache-2.0). The project does not bundle Microsoft Office, LibreOffice, proprietary fonts, or user documents. Font availability and permission to distribute document content remain the responsibility of the document owner.
