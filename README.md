# Word / PDF → 高還原 HTML

Python 桌面工具與 CLI，支援 `.doc`、`.docx`、`.pdf`，輸出可直接用瀏覽器開啟的離線 HTML。適合申請書、契約、表格與需要固定版面的文件。

桌面介面預設「版面重建 HTML」：文字與勾選框可編輯、線條使用 CSS、圖形另外存檔，輸出 HTML 與配套 assets 資料夾。CLI 為相容既有指令仍預設 `visual`，使用 `--output-mode layout` 啟用版面重建。

**目前未達成任意掃描 PDF 一鍵產生高還原、完整語意且無須核對的 HTML。** `layout` 保留元素位置，減少表格重排失真；OCR、字型、勾選狀態與業務欄位意義仍可能出錯。以下清楚區分已重建內容與圖片保留內容，不把圖片當成結構化成果。

## 掃描 PDF → 可編輯版面重建

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[word,layout]"
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\掃描表單.pdf" -o "outputs\表單-layout.html" --output-mode layout
```

安裝後也可以雙擊 [start_gui.cmd](start_gui.cmd)，選檔、按「開始轉換」。版面模式使用套件內附的 RapidOCR / PP-OCRv6 模型，模型路徑明確指定；轉換時不下載模型、不上傳文件，也不需要 Tesseract。模型缺少會失敗回報。OCR 在子程序執行，使用 `--ocr-timeout` 限制每頁時間。`--ocr-dpi` 預設 300；Tesseract 的語言、PSM、執行檔及 tessdata 選項只適用另外兩種模式。

輸出包含：

- HTML：可見文字 `<span contenteditable>`、真正 `<input type="checkbox">`、CSS `border` 線條及底色。座標單位為 PDF point，依頁面原位置擺放，不重新流動排版。
- assets 資料夾：共用 [layout.css](src/document_to_html/resources/layout.css)、[layout.js](src/document_to_html/resources/layout.js)、圖片與 `document.json`。HTML 沒有 Base64 圖片；線條不是圖片編碼。工程師可用元素 ID、`data-region` 與 JSON 座標綁定前端欄位。
- `document.json`：逐頁元素、文字、信心分數、候選字型、勾選框、偵測到的表格儲存格群組、圖片片段及處理限制。座標和表格分組是幾何推論，不是已驗證的業務資料模型。ID 在同份輸出中固定，重新辨識不保證不變。
- Logo / 彩色圖形：保留獨立 PNG。其他未辨識像素也保留為標示清楚的 PNG 片段。這些部分不能當成已結構化或可編輯文字；可用「標示待核對區域」查看。
- 原稿比對：只在使用者勾選「顯示原稿比對」時顯示整頁參考 PNG，並停用編輯。正常模式及列印不使用這張圖片當背景。

開啟 HTML 後可以改文字與勾選狀態，按「儲存修改後 HTML」下載修改版本，放在原 HTML 所在資料夾後重新開啟（旁邊要保留原 assets 資料夾）。也能「匯出欄位 JSON」接續前端開發。儲存不會回寫來源 PDF、呼叫 API 或自動寫入業務資料庫。覆蓋轉換使用新的 assets 資料夾，保留舊資料夾，避免破壞先前儲存的 HTML；不再使用的舊版本可自行清理。

可維護性的範圍：內容、樣式、程式與圖片分離；文字與勾選框可直接綁定資料。但不是工程師人工設計的響應式頁面，也不能可靠推回所有 `table` 合併關係、欄位名稱與驗證規則。長文字會縮放至既有框內；需要自動換行、增列、重新分頁時仍須重新設計表單。

字型從本機已安裝字型中比較候選與筆畫粗細，不嵌入或散布 Windows 字型；其他電腦缺少同字型會有差異。傾斜超過 5 度及文字量與位置明顯矛盾的辨識區域目前保留圖片；直排、手寫、遮擋、低清晰度與複雜底圖不保證還原。勾選框是影像幾何推論，可能與中文字形混淆。所有頁面均標記 `needs-review`，高信心分數也不是正確率。

參考 [RapidOCR 官方原始碼與使用說明](https://github.com/RapidAI/RapidOCR)。套件固定版本；升級 OCR 模型後須重新核對文件與輸出格式。

驗證指令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,word,layout]"
.\.venv\Scripts\python.exe -m pytest --browser-channel msedge --ocr-integration
.\.venv\Scripts\python.exe scripts\verify_layout.py "C:\Documents\掃描表單.pdf" "outputs\表單-layout.html" "artifacts\layout-check"
```

驗證會檢查編輯、勾選、儲存後重新開啟、原稿比對、列印頁數、JavaScript 錯誤及網路請求，另產生逐頁截圖與前景差異圖。前景像素 F1 採 1 像素容許誤差，**不是中文字準確率、數值正確率或完整結構化比例**。不以空白背景像素比例宣稱「高度還原」。

## 還原方式與限制

以下為 CLI 預設 `visual` 高還原模式。需要可編輯原位置文字與 CSS 線條時，優先使用上方 `layout`；下方舊 `structured` 模式為表格重排實驗。

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

### 結構化 HTML（實驗）

當你需要一般工程師能修改的 `<table>`、`<td>`、`rowspan`、`colspan` 與 CSS `border`，可安裝額外套件並選擇「輸出模式 → 結構化 HTML（實驗）」：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[structure]"
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\申請書.pdf" -o "outputs\申請書-structured.html" --output-mode structured
```

- 使用 `--ocr-dpi`（預設 300）分析頁面格線；此模式不使用 `--dpi`。Word 會先匯出 PDF。
- 完整閉合格線重建為表格，合併儲存格轉成 `rowspan` / `colspan`；未形成表格的長線段以 CSS 邊框呈現，文字以可見段落定位。沒有背景圖片、Base64 圖片或透明 SVG 文字層。
- 原生文字保留；掃描內容使用 Tesseract。偵測到的儲存格會分開辨識，避免跨欄合併文字。自動版面（PSM 3）在儲存格內改用單一區塊（PSM 6）；其他 PSM 依使用者設定。單頁 OCR 共用 `--ocr-timeout` 時間上限。
- 可點擊文字或空白儲存格直接試改。這是 `contenteditable` 預覽，**不會自動儲存、回寫原 PDF 或建立業務欄位綁定**；重新載入會還原。需留存可列印目前頁面。輸入長文字後請再次核對列高、重疊與分頁。
- 原始碼有縮排、區塊註解、表格及儲存格 ID。ID 只用於這次輸出，重新辨識可能變動；工程師仍須定義正式欄位名稱、資料模型、驗證與儲存流程。
- **這是實驗性的結構重建，不保證像素一致。** 中文字型、文字順序、格線顏色與粗細可能改變；Logo、照片、印章、手寫筆跡與底色不保留。勾選符號可能被 OCR 認錯，不會自動生成可信的勾選欄位。無格線表格、斜線、傾斜掃描與直排文字尚未可靠支援。
- 跨頁表格逐頁獨立，必要時在頁緣補框；漏線可能造成錯誤合併。未辨識到完整儲存格的區域以虛線標記，低信心文字以橙色點線提示，兩者皆須人工核對。不能將 OCR 金額或勾選結果直接當成已驗證資料。
- 使用固定紙張寬度，窄螢幕以水平捲動檢視。瀏覽器列印請選原始尺寸並關閉頁首／頁尾；大量修改後不保證原分頁。

格線偵測參考 [OpenCV 官方形態學線段擷取說明](https://docs.opencv.org/4.13.0/dd/dd7/tutorial_morph_lines_detection.html)。HTML 不含 JavaScript 或遠端請求；所有辨識在本機執行。

開發驗證（需已安裝 OCR 與瀏覽器）：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,structure]"
.\.venv\Scripts\python.exe -m pytest --browser-channel msedge --ocr-integration
.\.venv\Scripts\python.exe scripts\verify_structured.py "outputs\申請書-structured.html" --output artifacts\structured-browser
```

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
