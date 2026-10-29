# Word / PDF → 高還原 HTML

Python 桌面工具與 CLI，支援 `.doc`、`.docx`、`.pdf`，輸出一份可直接用瀏覽器開啟的離線 HTML。適合申請書、契約、表格與需要固定版面的文件。

## 還原方式與限制

- PDF 由 PDFium 逐頁渲染為 **無損 PNG**，預設 200 DPI，可選 300 / 600 DPI。保留頁面外觀、線條、圖片與 PDF 中的字型呈現；HTML 內嵌圖片，無 CDN、無 JavaScript、無外部資源。
- 在圖片上疊加透明 HTML 文字層，可選取、複製與使用瀏覽器搜尋。文字順序、選取精度取決於 PDF 文字資料；直排、旋轉文字、連字及錯誤編碼可能影響文字層，但不改變頁面影像。
- Word 先使用 **Microsoft Word** 或 **LibreOffice** 匯出 PDF，再使用相同流程。`auto` 優先 Word，只有 Word 不可用才改用 LibreOffice；文件轉換失敗不會悄悄改換引擎。
- **這是固定版面的視覺還原，不是可編輯的語意 HTML 表格。** 放大超過輸出解析度會看見像素；HTML 的圖片不是向量。高 DPI 可提高清晰度，但檔案較大。
- Word 排版取決於 Office 引擎、版本與已安裝字型。若已經有正確的原始 PDF，直接轉 PDF 通常比重新排版 Word 更一致。LibreOffice 和 Word 的換頁位置可能不同，不保證兩者與既有 PDF 一致。
- 掃描文件保留影像，不內建 OCR；沒有文字資料的頁面會提出提醒。PDF 表單會呈現目前的外觀，但不轉為互動表單；連結、附件、批註互動與巨集不會帶入 HTML。
- 瀏覽器列印會依各頁原始尺寸設定紙張。請使用 100% 縮放、關閉瀏覽器頁首與頁尾；混合紙張尺寸仍受瀏覽器與印表機支援限制。

## 安裝

需要 **Python 3.11 以上**。Windows 建議使用 python.org 的 Python（包含 Tkinter）；Linux GUI 另外安裝系統的 `python3-tk`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Word 輸入至少需要以下一項：

1. Windows 已安裝桌面版 Microsoft Word，並安裝 COM 相依套件：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[word]"
   ```

2. 安裝 [LibreOffice](https://www.libreoffice.org/)。程式會搜尋 PATH 與常見安裝位置，也可使用 `--libreoffice` 或 `LIBREOFFICE_PATH` 指定執行檔。

PDF 輸入不需要安裝 Office。

## 桌面介面

```powershell
.\.venv\Scripts\python.exe -m document_to_html --gui
```

Windows 安裝完成後也可雙擊 [start_gui.cmd](start_gui.cmd)。選擇來源與輸出位置，設定 DPI，按「開始轉換」。完成後可按「開啟 HTML」。來源 Word 與 PDF 即使同名，介面建議的輸出名稱也會加上原副檔名，避免互相覆蓋。

## 命令列

```powershell
# PDF → 單一 HTML
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.pdf" -o "outputs\申請書-pdf.html"

# 舊版 Word，指定 LibreOffice 與 300 DPI
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.doc" -o "outputs\申請書-word.html" --backend libreoffice --dpi 300

# 使用 Microsoft Word 的排版引擎
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.docx" -o "outputs\申請書-word.html" --backend word

# 加密 PDF：密碼在終端隱藏輸入，不放在命令列參數或設定檔
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\加密.pdf" --ask-password

# 已確認要覆蓋既有 HTML 時才加入 --overwrite
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.pdf" -o "outputs\申請書-pdf.html" --overwrite
```

其他選項：`--no-text-layer`、`--timeout 120`、`--max-pages 200`、`--libreoffice "C:\Program Files\LibreOffice\program\soffice.com"`。不指定 `-o` 時輸出至來源旁的同名 HTML；既有檔案預設不覆蓋。

## Python API

```python
from document_to_html import ConversionOptions, convert

result = convert(
    "申請書.pdf",
    "outputs/申請書.html",
    options=ConversionOptions(dpi=300),
    progress=lambda current, total: print(f"{current}/{total}"),
)
print(result.output, result.pages, result.backend)
for warning in result.warnings:
    print(warning)
```

PDFium 不是 thread-safe；同一程序內請循序呼叫 API。大量平行工作請使用不同程序，並自行限制同時工作數。桌面介面只允許一個轉換工作。

## 資料與安全

- 轉檔程式不使用雲端服務、API Key 或網路上傳。輸出的 HTML 包含完整文件影像與可擷取文字，應視為與來源同等敏感的資料。
- Word 巨集會關閉、自動連結更新會停用；LibreOffice 使用獨立暫存使用者設定，並在該設定檔停用自動更新，不更改日常 Office 設定。這些措施不是惡意文件沙箱，請在受管理的環境處理可信任文件，並持續更新 Python、Office 與 PDFium。
- Microsoft Word 使用獨立 COM 工作程序，並對新建 Word 程序套用 kill-on-close 工作物件；不對原有 Word 程序執行關閉或終止。此引擎設計給互動桌面，不適合作為無人值守的 Windows 服務。
- 預設限制來源 100 MiB、200 頁、每頁 5,000 萬像素及 20 萬文字字元；Office 轉檔預設逾時 120 秒。這不是整份 PDF 的硬性 CPU / 記憶體沙箱。
- 輸出先寫暫存檔，成功才發布。未指定覆蓋時，使用同磁碟 hard link 原子建立輸出，避免轉換期間出現同名檔案而被覆蓋；目的地需支援 hard link（例如 NTFS、ext4）。失敗會清除暫存 HTML；Office 中間 PDF 在結束時清除。
- [.gitignore](.gitignore) 排除來源文件、HTML、圖片、環境與本機驗證產物；請不要將實際業務文件加入 Git。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,word]"
.\.venv\Scripts\python.exe -m pytest

# 有安裝 Edge 時，加入真正的瀏覽器驗證
.\.venv\Scripts\python.exe -m pytest --browser-channel msedge
```

測試以程式產生合成 PDF，不含業務文件。涵蓋逐像素還原、四種頁面旋轉、文字層、無文字頁面、HTML 注入防護、覆蓋與競態保護、損毀輸入、資源上限與 Word adapter 流程。GitHub Actions 在 Windows / Linux、Python 3.11 / 3.14 執行核心測試，另外以 Chromium 執行搜尋、列印與畫面比對。

實際 Office 相容性仍需在安裝目標 Office 的桌面環境驗證。請參考 [驗證紀錄](docs/VALIDATION.md)。

## 程式結構

- [轉換流程](src/document_to_html/converter.py)：驗證、暫存資料與安全發布。
- [Office 引擎](src/document_to_html/backends.py)：Word / LibreOffice adapters。
- [HTML 產生器](src/document_to_html/html_writer.py)：PDFium 圖像、文字座標與列印樣式。
- [桌面介面](src/document_to_html/gui.py) 與 [命令列](src/document_to_html/cli.py)。

第三方元件授權請見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
