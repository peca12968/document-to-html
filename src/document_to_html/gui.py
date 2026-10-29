"""Small desktop front end. The UI thread never calls PDFium."""

from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .converter import ConversionOptions, ConversionResult, convert
from .errors import ConversionError


class ConverterWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Word / PDF → 高還原 HTML")
        self.root.geometry("760x440")
        self.root.minsize(640, 400)
        self.source = tk.StringVar()
        self.destination = tk.StringVar()
        self.dpi = tk.StringVar(value="200")
        self.backend = tk.StringVar(value="auto")
        self.password = tk.StringVar()
        self.text_layer = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="選擇 Word 或 PDF，產生可離線開啟的單一 HTML。")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.result: ConversionResult | None = None
        container = ttk.Frame(root, padding=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)
        ttk.Label(container, text="Word / PDF → HTML", font=("Microsoft JhengHei", 20, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(container, text="保留原始頁面外觀、表格與分頁；文字層供選取與搜尋。", wraplength=650).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 18))
        ttk.Label(container, text="來源檔案").grid(row=2, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(container, textvariable=self.source).grid(row=2, column=1, sticky="ew")
        ttk.Button(container, text="選擇檔案", command=self.choose_source).grid(row=2, column=2, padx=(10, 0))
        ttk.Label(container, text="輸出 HTML").grid(row=3, column=0, sticky="w", pady=12)
        ttk.Entry(container, textvariable=self.destination).grid(row=3, column=1, sticky="ew")
        ttk.Button(container, text="另存位置", command=self.choose_destination).grid(row=3, column=2, padx=(10, 0))
        options = ttk.Frame(container)
        options.grid(row=4, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(options, text="DPI").pack(side="left")
        ttk.Combobox(options, textvariable=self.dpi, values=["150", "200", "300", "600"], width=6, state="readonly").pack(side="left", padx=(6, 16))
        ttk.Label(options, text="Word 引擎").pack(side="left")
        ttk.Combobox(options, textvariable=self.backend, values=["auto", "word", "libreoffice"], width=12, state="readonly").pack(side="left", padx=(6, 16))
        ttk.Checkbutton(options, text="可選取文字層", variable=self.text_layer).pack(side="left")
        password_frame = ttk.Frame(container)
        password_frame.grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(password_frame, text="PDF 密碼（選填）").pack(side="left")
        ttk.Entry(password_frame, textvariable=self.password, show="●", width=24).pack(side="left", padx=8)
        actions = ttk.Frame(container)
        actions.grid(row=6, column=0, columnspan=3, sticky="w", pady=12)
        self.convert_button = ttk.Button(actions, text="開始轉換", command=self.start)
        self.convert_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="開啟 HTML", command=self.open_result, state="disabled")
        self.open_button.pack(side="left", padx=12)
        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.grid(row=7, column=0, columnspan=3, sticky="ew")
        ttk.Label(container, textvariable=self.status, wraplength=680).grid(row=8, column=0, columnspan=3, sticky="w", pady=10)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def choose_source(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(filetypes=[("Word / PDF", "*.doc *.docx *.pdf")])
        if path:
            self.source.set(path)
            # Different extensions with the same stem must not collide.
            source = Path(path)
            self.destination.set(str(source.with_name(f"{source.stem}-{source.suffix[1:]}.html")))

    def choose_destination(self) -> None:
        if self.busy:
            return
        path = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if path:
            self.destination.set(path)

    def start(self) -> None:
        if self.busy:
            return
        if not self.source.get().strip() or not self.destination.get().strip():
            messagebox.showerror("缺少路徑", "請選擇來源檔案與輸出路徑。")
            return
        overwrite = Path(self.destination.get()).exists()
        if overwrite and not messagebox.askyesno("覆蓋確認", "指定 HTML 已存在，是否覆蓋？"):
            return
        options = ConversionOptions(dpi=int(self.dpi.get()), backend=self.backend.get(),
                                    text_layer=self.text_layer.get(), overwrite=overwrite)
        source, destination, password = self.source.get(), self.destination.get(), self.password.get() or None
        self.password.set("")
        self.busy = True
        self.result = None
        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.status.set("正在準備文件，Word 轉檔可能需要一些時間…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def work() -> None:
            try:
                result = convert(source, destination, options=options, password=password,
                                 progress=lambda current, total: self.events.put(("progress", (current, total))))
                self.events.put(("done", result))
            except ConversionError as error:
                self.events.put(("error", str(error)))
            except Exception:
                self.events.put(("error", "發生未預期錯誤；請使用命令列檢查或回報問題。"))

        # One worker only; PDFium operations are serialized.
        threading.Thread(target=work, daemon=False).start()

    def poll(self) -> None:
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            self.progress.stop()
            if kind == "progress":
                current, total = value
                self.progress.configure(mode="determinate", maximum=total, value=current)
                self.status.set(f"轉換中：{current}/{total} 頁")
            else:
                self.busy = False
                self.convert_button.configure(state="normal")
                if kind == "done":
                    self.result = value
                    self.open_button.configure(state="normal")
                    self.status.set(f"完成 {value.pages} 頁（{value.backend}）：{value.output}")
                    if value.warnings:
                        messagebox.showwarning("轉換完成，部分頁面沒有文字層", "\n".join(value.warnings[:8]))
                else:
                    self.status.set("轉換失敗。")
                    messagebox.showerror("轉換失敗", str(value))
        self.root.after(100, self.poll)

    def open_result(self) -> None:
        if self.result:
            webbrowser.open(self.result.output.as_uri())

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo("正在轉換", "請等待目前轉換完成後再關閉視窗。")
            return
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ConverterWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
