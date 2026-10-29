# 驗證紀錄

日期：2026-10-29。實際文件與產物僅保留於本機，本儲存庫不包含申請書內容或截圖。

## 目前最終版本確認

使用者選定 `f44f4b1`（1.1.0）的「高還原圖片」流程；轉換核心與該版本一致。只補充介面的模式標示、啟動器的本機原始碼路徑與版本說明。

- `python -m pytest -q --browser-channel msedge --ocr-integration`：**41 passed**，包含實際 Tesseract 與瀏覽器驗證。
- 兩份使用者提供的掃描 PDF 以預設 200 DPI 轉換，均輸出 2 頁、逐頁執行 OCR；瀏覽器搜尋成功，列印均為 2 頁。
- 內嵌 PNG 與來源 PDF 以相同 PDFium 參數獨立渲染的影像，逐像素一致。
- 兩份 HTML 的各頁瀏覽器截圖與內嵌 PNG，在原生像素尺寸下平均絕對像素差均為 0。
- 390px 行動版無水平溢出，HTTP(S) 外部請求及 JavaScript 錯誤均為 0。
- 指定副本與主要專案的 editable 安裝已各自指向自己的原始碼；桌面介面啟動檢查通過。

以上是影像與功能驗證，不代表 OCR 文字零誤差，也不代表輸出為可編輯的語意表單。

## 本機環境

- Windows、Python 3.14.3。
- pypdfium2 5.14.0、Pillow 13.0.0、pywin32 312。
- Microsoft Word 2013；Chromium-based Microsoft Edge。

## 1.0 版原始文件驗證

使用同一份申請書的舊版 DOC 與既有 PDF，分別輸出 300 DPI HTML。

| 檢查 | PDF 輸入 | DOC 輸入 |
| --- | --- | --- |
| 引擎 | PDFium | Microsoft Word → PDFium |
| 輸出頁數 | 4 | 4 |
| HTML 檔案大小 | 6,476,752 bytes | 6,474,890 bytes |
| 可擷取非空白字元 | 3,731 | 3,735 |
| 瀏覽器搜尋連續文字 | 通過 | 通過 |
| 瀏覽器列印 PDF 頁數 | 4 | 4 |
| 390px 行動裝置寬度無水平溢出 | 通過 | 通過 |
| 開啟 HTML 的 HTTP(S) 請求 | 0 | 0 |
| 各頁瀏覽器截圖與內嵌 PNG 的平均絕對像素差 | 全部 0 | 全部 0 |

像素比對在內嵌 PNG 原生像素尺寸、device scale factor 1 下進行，不代表可以任意放大而不失真，也不代表 Word 排版與既有 PDF 永遠相同。已目視檢查首頁：表格框線、紅色標記、直排提示與中文字體均可辨識，版面保留。

瀏覽器列印紙張約為 594.96 × 841.92 pt。原始 PDF 頁寬約 595.32 pt；瀏覽器對紙張尺寸有小幅量化誤差，這不等於原生 Office 的精密印前輸出。

## 1.0 版自動測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q --browser-channel msedge
```

結果：**23 passed**，包含兩項真實瀏覽器測試。合成 PDF 測試驗證 0 / 90 / 180 / 270 度旋轉的無損頁面影像、完整文字行、資源與覆蓋防護。瀏覽器測試額外驗證搜尋、原生尺寸截圖、列印與行動版尺寸。

另以 Tkinter 桌面介面執行合成 PDF 轉換，確認兩頁輸出完成、進度更新與「開啟 HTML」按鈕啟用；`pip check` 未發現相依衝突。

重跑實際 HTML 的瀏覽器檢查：

```powershell
.\.venv\Scripts\python.exe scripts\verify_html.py outputs\document.html --output artifacts\browser --channel msedge
```

此工具會將包含文件內容的截圖與列印 PDF 寫至指定資料夾。建議固定使用被 Git 忽略的 `artifacts/`，不要提交這些產物。

## 1.1 版 OCR 驗證

本機使用 Tesseract 5.5.0，已安裝 `chi_tra`、`chi_tra_vert` 與 `eng` 模型。全部辨識在本機執行。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --browser-channel msedge --ocr-integration
```

結果：**41 passed**。新增項目包括實際繁體中文與英文掃描辨識、連續詞句搜尋、混合頁面的原生文字遮蔽、強制替換、停用 OCR、低信心度提醒、缺模型與執行檔、逾時、座標限制、HTML escaping，以及暫存檔清理。

另外將原本四頁 PDF 完全光柵化，先驗證每頁原生文字數皆為 0，再以預設 `auto / chi_tra+eng / 300 DPI / PSM 3` 轉換，四頁均產生 OCR 文字層，共擷取 4,077 個字元（此計數包含部分空白，**不是準確率**）。四頁皆有低信心度結果，提醒數分別為 45、7、43、8 行；複雜表格與直排內容須核對原圖。原始檔、掃描副本、OCR HTML 與報告均未加入 Git。

掃描版 HTML 的瀏覽器檢查通過：四頁原生尺寸截圖與內嵌 PNG 的平均絕對像素差皆為 0、文字搜尋成功、列印為四頁、行動版無水平溢出，HTTP(S) 請求數為 0。另以桌面介面選擇「單一區塊」辨識合成繁體中文掃描頁，確認「申購申請書」出現在文字層且完成後可開啟 HTML。

## 尚未確認的環境

- 此電腦的 LibreOffice 24.8 實際轉檔曾觸發更新程序，停用專用設定檔的更新後仍逾時。因此本次實際 DOC 成功結果使用 Microsoft Word；LibreOffice adapter 的參數、失敗回報與設定檔由自動測試驗證，**未宣稱此電腦的 LibreOffice 已成功轉換該文件**。
- Word 引擎須有可用桌面與已授權 Word，未驗證 Windows Service 部署。
- 巨型文件、複雜直排文字的選取順序、手寫辨識準確率及互動式 PDF 表單不在本次成功範圍。掃描 OCR 已驗證上述案例，未保證任意文件皆能正確辨識。
