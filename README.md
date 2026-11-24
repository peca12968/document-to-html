# Word / PDF → 高還原 HTML

Python 桌面工具與 CLI，支援 `.doc`、`.docx`、`.pdf`，輸出一份可直接用瀏覽器開啟的離線 HTML。適合申請書、契約、表格與需要固定版面的文件。

## 目前採用的穩定版本

高還原圖片沿用 `f44f4b1`（1.1.0）的 PDF 渲染與 Word 匯出。1.3.0 另外提供「結構化 HTML＋CSS」模式，產生供專案開發使用的靜態範本。

1.3.1 修正原生文字 PDF 的表單編排：優先讀取字級、向量框線與欄列尺寸，保留紅字、紅框、虛線、直排側註及簽章留白。圖片與勾選區仍是內嵌 PNG，正文與框線是可維護的 HTML＋CSS。

1.3.2 改善「高還原圖片」的透明文字層：原生文字保留每字起點，OCR 保留每詞範圍，減少整行拉伸與跨欄串字。有安裝 `[template]` 時，共用範本模式的表格偵測，依儲存格分組、排序；沒有安裝時仍可轉換，以基線及間距分組。頁面 PNG 不變，文字層仍採 SVG 以保留旋轉及位置精度，沒有改成可編輯的可見表格，也沒有更換 OCR 引擎。

桌面介面預設「結構化 HTML＋CSS」；命令列保留 `visual` 預設值，以相容既有批次。範本先提供靜態內容，後續可由 AI 加入輸入框、資料綁定及驗證。詳細規格見 [範本輸出規格](docs/TEMPLATE_OUTPUT.md)。

雙擊 [start_gui.cmd](start_gui.cmd) 啟動。啟動器會指定目前專案的原始碼路徑，避免複製專案及虛擬環境後，誤載入另一個資料夾的版本。自行使用命令列時，先在目前資料夾重新執行 `python -m pip install -e .`，不要直接沿用另一個資料夾的 editable 安裝。

## 結構化 HTML＋CSS 範本

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[word,template]"
.\.venv\Scripts\python.exe -m document_to_html "C:\Documents\表單.pdf" --output-mode structured -o "outputs\表單-template.html"
```

輸出為單一 HTML，CSS 集中在頁首，沒有 JavaScript、編輯工具列或框架依賴。使用段落、分層區段、清單、真正的表格與合併儲存格；欄位使用有 `data-label` 的文字及留白元素，初始不建立 `input`。Logo、可辨識的彩色圖形及符合範圍限制的 PDF 圖片，以 `<img src="data:image/png;base64,...">` 內嵌，不把整頁當成範本圖片。

範本不使用逐字絕對座標或固定正文高度；修改段落、新增表格列會自然排版。樣式集中在 [template.css](src/document_to_html/resources/template.css)，轉換時嵌入 HTML，所以產出不依賴此檔案。原本已有的文字、金額及姓名會保留，**不會自行清除填寫資料**。

原生表單使用 [native-template.css](src/document_to_html/resources/native-template.css)，以 `colgroup`、`rowspan`、`colspan` 保留欄列比例，集中產生可共用的字級、顏色及間距類別。頁面使用最小高度，表格列高度保留原稿留白；內容增加時仍可長高。範本不是逐字定位，也不把整頁改成圖片。原生表單在窄螢幕保留紙張寬度並提供水平捲動，避免表格比例被擠壓。

目前優先採用原生編排的條件是每頁具有足夠文字、未旋轉、沒有巢狀 Form XObject，且沒有占頁面大面積的掃描圖片；其餘文件繼續使用原有的掃描／一般範本流程。`--ocr always` 仍強制使用 OCR 流程。Wingdings 等私人字元以 `.source-symbol` 小圖片保留，與 `.choice` 勾選容器分開，避免把圈號數字誤當成 checkbox。

勾選框與可辨識的勾記也會裁切成原稿小圖片，以 `.choice` 容器和 `data-choice` 識別碼保留，圖片使用 `.choice-image`。後續可在同一容器加入透明 checkbox 或隱藏的勾選控制層。初始範本不產生互動控制項、不推定布林值，也不移除原稿已存在的勾記；若要從空白狀態開始填寫，請提供未勾選的原稿。未成功定位的符號可能仍以 OCR 文字呈現，需與原稿核對。

本機使用 RapidOCR 內附模型分析掃描頁，300 DPI 為預設分析解析度，可用 `--ocr-dpi`、`--ocr-timeout` 調整；不下載模型、不上傳文件。Tesseract 的語言與 PSM 選項只適用高還原圖片模式。缺少範本相依套件或模型時會明確回報，不改用其他引擎偷偷產生不同結果。

**這是自動整理的範本初稿，仍須核對 OCR、欄位配對、勾選狀態及表格合併。** 圖形判斷採幾何與色彩規則，可能漏掉黑白掃描圖形或誤包含彩色文字；跨頁表格暫時分頁整理，列印頁數可能增加。輸出警告與原始碼註解指出部分待核對區域，並非所有錯誤都能自動偵測。此模式不保證任意 PDF 的外觀或語意完全還原。

輸出是一般 `.html`，使用 `@page` 而非 `@@page`。要加入 Razor 專案時，由專案端處理 Layout、CSS 的 `@` 跳脫及文字中的 Razor 符號；不要直接將不可信文字當成 Razor 程式碼執行。

## 還原方式與限制

- PDF 由 PDFium 逐頁渲染為 **無損 PNG**，預設 200 DPI，可選 300 / 600 DPI。保留頁面外觀、線條、圖片與 PDF 中的字型呈現；HTML 內嵌圖片，無 CDN、無 JavaScript、無外部資源。
- 在圖片上疊加透明 SVG 文字層，可選取、複製與使用瀏覽器搜尋。`text-region` 搭配 `data-table`、`data-row`、`data-column` 標示已辨識的儲存格；原生文字以座標列表保留逐字起點，OCR 以 `tspan` 保留詞的位置。文字順序、選取精度仍取決於來源資料及表格辨識結果；直排、連字及錯誤編碼可能影響文字層，但不改變頁面影像。
- Word 先使用 **Microsoft Word** 或 **LibreOffice** 匯出 PDF，再使用相同流程。`auto` 優先 Word，只有 Word 不可用才改用 LibreOffice；文件轉換失敗不會悄悄改換引擎。
- **這是固定版面的視覺還原，不是可編輯的語意 HTML 表格。** 放大超過輸出解析度會看見像素；HTML 的圖片不是向量。高 DPI 可提高清晰度，但檔案較大。
- Word 排版取決於 Office 引擎、版本與已安裝字型。若已經有正確的原始 PDF，直接轉 PDF 通常比重新排版 Word 更一致。LibreOffice 和 Word 的換頁位置可能不同，不保證兩者與既有 PDF 一致。
- 掃描文件可透過本機 Tesseract 辨識繁體中文與英文，再疊加透明 SVG 文字層。預設自動處理無文字頁面及包含圖片的混合頁面，保留原始頁面影像。PDF 表單會呈現目前的外觀，但不轉為互動表單；連結、附件、批註互動與巨集不會帶入 HTML。
- 瀏覽器列印會依各頁原始尺寸設定紙張。請使用 100% 縮放、關閉瀏覽器頁首與頁尾；混合紙張尺寸仍受瀏覽器與印表機支援限制。

## 重現兩種輸出

在安裝 `.[template]` 的環境執行下列指令。`sample-output` 是新目錄，會取得一頁合成申請表 `sample-form.pdf` 和兩份可離線開啟的 `visual.html`、`structured.html`。

```sh
python -m scripts.export_demo --directory sample-output
```

圖片版保留 320 × 427 像素的頁面影像，瀏覽器可搜尋 `Signature`。結構版的 `Name` 與 `Example` 是同列的 HTML 儲存格。示範資料由實際轉檔輸出擷取，包含來源 SHA-256、PNG、可搜尋文字和表格欄列。Playwright 另開啟兩份原始輸出，驗證圖片解碼、瀏覽器搜尋及表格語意。[展示資料](examples/conversion-demo.json) · [瀏覽器驗證](tests/test_export_demo.py)

### 只轉換指定頁面

```sh
python -m document_to_html source.pdf --pages 2,5-7 -o excerpt.html
python -m document_to_html source.pdf --pages 2,5-7 --output-mode structured -o excerpt-template.html
python -m scripts.export_page_demo --directory selected-output
```

頁碼從 1 開始，可用逗號分隔單頁和含頭尾的範圍。輸出按來源頁碼排列，重複頁碼只輸出一次。`--max-pages` 限制輸出頁數。Word 先經選定的排版引擎匯出 PDF，頁碼以該次匯出的結果為準。桌面介面可在「頁碼」輸入相同格式，留空會轉換全部。

兩種輸出都保留原頁碼。進度顯示已處理的選取頁數，OCR 提醒仍使用來源頁碼。輸入超過來源頁數等無效範圍時，既有 HTML 會保留。示範從四頁合成文件選取 `4,2`，兩種輸出都依來源順序留下第 2、4 頁，圖片版可直接在瀏覽器搜尋和列印這兩頁。[實際展示資料](examples/page-selection-demo.json) · [選頁驗證](tests/test_page_selection.py)

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
- [OCR 引擎](src/document_to_html/ocr.py)：Tesseract 呼叫、TSV 解析與辨識選項；[OCR 文字層](src/document_to_html/ocr_layer.py)：原生文字遮蔽；[文字層分組](src/document_to_html/visual_text.py)：共用儲存格偵測、閱讀順序及座標對齊。
- [桌面介面](src/document_to_html/gui.py) 與 [命令列](src/document_to_html/cli.py)。

第三方元件授權請見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
