# Word / PDF → 高還原 HTML

Python 桌面工具與 CLI，支援 `.doc`、`.docx`、`.pdf`，輸出一份可直接用瀏覽器開啟的離線 HTML。適合申請書、契約、表格與需要固定版面的文件。

## 還原方式與限制

- PDF 由 PDFium 逐頁渲染為 **無損 PNG**，預設 200 DPI，可選 300 / 600 DPI。保留頁面外觀、線條、圖片與 PDF 中的字型呈現；HTML 內嵌圖片，無 CDN、無 JavaScript、無外部資源。
- 在圖片上疊加透明 HTML 文字層，可選取、複製與使用瀏覽器搜尋。文字順序、選取精度取決於 PDF 文字資料；直排、旋轉文字、連字及錯誤編碼可能影響文字層，但不改變頁面影像。
- Word 先使用 **Microsoft Word** 或 **LibreOffice** 匯出 PDF，再使用相同流程。`auto` 優先 Word，只有 Word 不可用才改用 LibreOffice；文件轉換失敗不會悄悄改換引擎。
- **這是固定版面的視覺還原，不是可編輯的語意 HTML 表格。** 放大超過輸出解析度會看見像素；HTML 的圖片不是向量。高 DPI 可提高清晰度，但檔案較大。
- Word 排版取決於 Office 引擎、版本與已安裝字型。若已經有正確的原始 PDF，直接轉 PDF 通常比重新排版 Word 更一致。LibreOffice 和 Word 的換頁位置可能不同，不保證兩者與既有 PDF 一致。
- 掃描文件可透過本機 Tesseract 辨識繁體中文與英文，再疊加透明 SVG 文字層。預設自動處理無文字頁面及包含圖片的混合頁面，保留原始頁面影像。PDF 表單會呈現目前的外觀，但不轉為互動表單；連結、附件、批註互動與巨集不會帶入 HTML。
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

### 掃描 PDF 的 OCR 安裝

需要另外安裝 **Tesseract 5**，以及 `chi_tra`（繁體中文）和 `eng`（英文）語言模型。Python 套件不會下載模型，也不會將文件傳到辨識服務。安裝來源請參考 [Tesseract 官方安裝說明](https://tesseract-ocr.github.io/tessdoc/Installation.html)。

- Windows：安裝時選取繁體中文模型；程式會搜尋 PATH 與 Program Files 下的 Tesseract-OCR。
- Ubuntu / Debian：`sudo apt-get install tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-eng`。
- 其他安裝位置：使用 `--tesseract` 或環境變數 `TESSERACT_PATH` 指定執行檔，`--tessdata` 指定模型資料夾。環境既有 `TESSDATA_PREFIX` 也會由 Tesseract 接收。
- 缺少執行檔、模型、辨識逾時或引擎失敗時會清楚回報，且不覆蓋既有輸出。只需保留圖片時可選擇 `--ocr off`。

文字頁且不含圖片時，不會啟動 Tesseract；純文字 PDF 仍可在未安裝 OCR 的環境轉換。

## 桌面介面

```powershell
.\.venv\Scripts\python.exe -m document_to_html --gui
```

Windows 安裝完成後也可雙擊 [start_gui.cmd](start_gui.cmd)。選擇來源與輸出位置，設定 DPI，按「開始轉換」。完成後可按「開啟 HTML」。來源 Word 與 PDF 即使同名，介面建議的輸出名稱也會加上原副檔名，避免互相覆蓋。

「圖片 OCR」提供「自動辨識／全部重辨識／關閉」，預設自動辨識。語言模型預設 `chi_tra+eng`；「版面」可選自動版面、單一區塊、零散文字或直排區塊。若簡單的橫排文字被自動版面切錯，可改選單一區塊。完成狀態會顯示執行 OCR 的頁數，低信心度結果會提出提醒。

## 命令列

```powershell
# PDF → 單一 HTML
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.pdf" -o "outputs\申請書-pdf.html"

# 掃描 PDF：預設自動 OCR，影像與 OCR 解析度可分別設定
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\掃描申請書.pdf" -o "outputs\掃描申請書.html" --dpi 300 --ocr auto --ocr-language chi_tra+eng

# 原本文字層亂碼時，重新辨識整頁，替換原本的文字層
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\文字異常.pdf" --ocr always

# 只保留原文字與影像、不執行 OCR
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.pdf" --ocr off

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

### OCR 的行為與調整

| 選項 | 行為 |
| --- | --- |
| `--ocr auto` | 無原生文字時辨識整頁；有原生文字且有圖片物件時，先在辨識副本遮蔽原生文字，再辨識剩餘內容。純原生文字頁跳過 OCR。 |
| `--ocr always` | 每頁完整辨識，輸出的文字層只使用 OCR 結果，避免與原生文字重複。 |
| `--ocr off` | 使用原生 PDF 文字；掃描頁只保留影像並提醒。 |
| `--no-text-layer` | 完全停用文字層與 OCR，只保留影像。 |
| `--ocr-dpi 300` | OCR 的獨立渲染解析度，與輸出圖片的 `--dpi` 分開；範圍 72–600。 |
| `--ocr-timeout 120` | 每頁辨識逾時秒數。 |
| `--ocr-psm 3` | 預設自動版面分析；單一文字區塊可用 6，零散文字可嘗試 11。 |
| `--ocr-min-confidence 0` | 預設保留有效辨識結果，低於 60 分的行會提出提醒；提高此門檻會捨棄低分詞，可能造成缺字。 |

OCR 的 TSV 輸出提供文字、座標與信心分數，再依文字行定位。中文字之間不會額外插入英文空格，讓連續詞句可搜尋；模型分數不是準確率百分比。參考 [Tesseract 官方命令列與 TSV 文件](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)。

**已知限制**：自動模式依據文字與圖片物件判斷，包含照片或標誌的頁面也可能觸發 OCR。已有完整隱藏文字層的掃描頁仍可能在遮蔽後辨識到殘影或雜訊。若圖片區塊與原生文字重疊，遮蔽可能影響辨識；向量輪廓文字若同頁已有其他原生文字且沒有圖片物件，不會自動觸發 OCR，可用 `always`。尚未自動校正歪斜或方向；直排可嘗試 `--ocr-language chi_tra_vert --ocr-psm 5`（需另裝模型），但未保證閱讀順序與選取精度。模糊影像、手寫、印章及複雜表格可能誤辨或漏字，請以原始影像為準。

## Python API

```python
from document_to_html import ConversionOptions, OcrOptions, convert

result = convert(
    "申請書.pdf",
    "outputs/申請書.html",
    options=ConversionOptions(dpi=300, ocr=OcrOptions(mode="auto", language="chi_tra+eng")),
    progress=lambda current, total: print(f"{current}/{total}"),
)
print(result.output, result.pages, result.backend)
print("執行 OCR 的頁碼：", result.ocr_pages)
for warning in result.warnings:
    print(warning)
```

PDFium 不是 thread-safe；同一程序內請循序呼叫 API。大量平行工作請使用不同程序，並自行限制同時工作數。桌面介面只允許一個轉換工作。

## 資料與安全

- 轉檔程式不使用雲端服務、API Key 或網路上傳。輸出的 HTML 包含完整文件影像與可擷取文字，應視為與來源同等敏感的資料。
- Word 巨集會關閉、自動連結更新會停用；LibreOffice 使用獨立暫存使用者設定，並在該設定檔停用自動更新，不更改日常 Office 設定。這些措施不是惡意文件沙箱，請在受管理的環境處理可信任文件，並持續更新 Python、Office 與 PDFium。
- Microsoft Word 使用獨立 COM 工作程序，並對新建 Word 程序套用 kill-on-close 工作物件；不對原有 Word 程序執行關閉或終止。此引擎設計給互動桌面，不適合作為無人值守的 Windows 服務。
- 預設限制來源 100 MiB、200 頁、每次頁面渲染 5,000 萬像素及每層 20 萬文字字元；Office 轉檔與每頁 OCR 預設逾時 120 秒。這不是整份 PDF 的硬性 CPU / 記憶體沙箱。
- OCR 使用獨立暫存 PNG 與不經 shell 的參數陣列啟動 Tesseract，成功或例外時均清除暫存圖片；辨識輸出不直接寫入日誌。文字會經 HTML escaping 才放入 SVG。
- 輸出先寫暫存檔，成功才發布。未指定覆蓋時，使用同磁碟 hard link 原子建立輸出，避免轉換期間出現同名檔案而被覆蓋；目的地需支援 hard link（例如 NTFS、ext4）。失敗會清除暫存 HTML；Office 中間 PDF 在結束時清除。
- [.gitignore](.gitignore) 排除來源文件、HTML、圖片、環境與本機驗證產物；請不要將實際業務文件加入 Git。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,word]"
.\.venv\Scripts\python.exe -m pytest

# 有安裝 Edge 時，加入真正的瀏覽器驗證
.\.venv\Scripts\python.exe -m pytest --browser-channel msedge

# 已安裝 Tesseract + chi_tra / eng 模型時，加入中英文掃描整合測試
.\.venv\Scripts\python.exe -m pytest --browser-channel msedge --ocr-integration
```

測試以程式產生合成 PDF，不含業務文件。涵蓋逐像素還原、四種頁面旋轉、文字層、OCR 三種模式、同頁混合內容、座標與信心分數、HTML 注入防護、覆蓋與競態保護、損毀輸入、資源上限與 Word adapter 流程。GitHub Actions 定義 Windows / Linux、Python 3.11 / 3.14 核心測試；Linux Chromium 工作另安裝 Tesseract 模型並執行中英文 OCR、搜尋、列印與畫面比對。帳號必須允許 Actions 執行；本機測試不受雲端帳務額度影響。

實際 Office 相容性仍需在安裝目標 Office 的桌面環境驗證。請參考 [驗證紀錄](docs/VALIDATION.md)。

## 程式結構

- [轉換流程](src/document_to_html/converter.py)：驗證、暫存資料與安全發布。
- [Office 引擎](src/document_to_html/backends.py)：Word / LibreOffice adapters。
- [HTML 產生器](src/document_to_html/html_writer.py)：PDFium 圖像、文字座標與列印樣式。
- [OCR 引擎](src/document_to_html/ocr.py)：Tesseract 呼叫、TSV 解析與辨識選項；[OCR 文字層](src/document_to_html/ocr_layer.py)：原生文字遮蔽與座標對齊。
- [桌面介面](src/document_to_html/gui.py) 與 [命令列](src/document_to_html/cli.py)。

第三方元件授權請見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
