"use strict";
// Geometry lives on .text-box; content lives in .editable-text. Applications can
// use element IDs or data-region to bind fields without decoding image data.
const canvas = document.createElement("canvas");
const context = canvas.getContext("2d");
const statusElement = document.getElementById("edit-status");
const textBoxes = Array.from(document.querySelectorAll(".text-box"));
const checkboxes = Array.from(document.querySelectorAll(".check-box"));

function fitText(box) {
  const text = box.querySelector(".editable-text");
  const fontSize = 32;
  const style = getComputedStyle(box);
  context.font = `${style.fontWeight} ${fontSize}px ${style.fontFamily}`;
  const metrics = context.measureText(text.textContent || " ");
  const inkWidth = Math.max(1, metrics.actualBoundingBoxLeft + metrics.actualBoundingBoxRight);
  const inkHeight = Math.max(1, metrics.actualBoundingBoxAscent + metrics.actualBoundingBoxDescent);
  const fontAscent = metrics.fontBoundingBoxAscent ?? fontSize * .8;
  const fontDescent = metrics.fontBoundingBoxDescent ?? fontSize * .2;
  const baseline = (fontSize - fontAscent - fontDescent) / 2 + fontAscent;
  const scaleX = box.getBoundingClientRect().width / inkWidth;
  const scaleY = box.getBoundingClientRect().height / inkHeight;
  text.style.fontSize = `${fontSize}px`;
  text.style.left = `${metrics.actualBoundingBoxLeft * scaleX}px`;
  text.style.top = `${(metrics.actualBoundingBoxAscent - baseline) * scaleY}px`;
  text.style.transform = `scale(${scaleX}, ${scaleY})`;
  box.dataset.review = String(Number(box.dataset.confidence) < 85);
}

function fitAll() {
  textBoxes.forEach(fitText);
  checkboxes.forEach(box => { box.style.fontSize = `${box.getBoundingClientRect().height * .85}px`; });
}

textBoxes.forEach(box => {
  const editor = box.querySelector(".editable-text");
  editor.addEventListener("input", () => {
    fitText(box);
    statusElement.textContent = "有未儲存的修改，請使用「儲存修改後 HTML」。";
  });
  editor.addEventListener("keydown", event => {
    if (event.key === "Enter") event.preventDefault();
  });
  editor.addEventListener("paste", event => {
    event.preventDefault();
    const value = (event.clipboardData?.getData("text/plain") || "").replace(/[\r\n]+/g, " ");
    const selection = getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0);
    range.deleteContents();
    const node = document.createTextNode(value);
    range.insertNode(node);
    range.setStartAfter(node);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
});
checkboxes.forEach(box => box.addEventListener("change", () => {
  statusElement.textContent = "有未儲存的勾選狀態，請使用「儲存修改後 HTML」。";
}));

document.getElementById("show-source").addEventListener("change", event => {
  document.querySelectorAll(".source-reference").forEach(image => { image.hidden = !event.target.checked; });
  // Prevent keyboard edits through the reference overlay as well as mouse edits.
  textBoxes.forEach(box => { box.querySelector(".editable-text").contentEditable = event.target.checked ? "false" : "plaintext-only"; });
  checkboxes.forEach(box => { box.disabled = event.target.checked; });
});
document.getElementById("show-review").addEventListener("change", event => {
  document.body.classList.toggle("review", event.target.checked);
});

function download(content, type, name) {
  const address = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = address;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(address), 1000);
}

document.getElementById("save-data").addEventListener("click", () => {
  const fields = [...textBoxes.map(box => ({ id: box.id, region: box.dataset.region,
    type: "text", text: box.querySelector(".editable-text").textContent,
    confidence: Number(box.dataset.confidence) })),
  ...checkboxes.map(box => ({ id: box.id, type: "checkbox", checked: box.checked }))];
  download(JSON.stringify({ schema_version: 1, fields }, null, 2), "application/json;charset=utf-8", "fields.json");
});

document.getElementById("save-html").addEventListener("click", () => {
  const clone = document.documentElement.cloneNode(true);
  checkboxes.forEach(box => {
    const saved = clone.querySelector(`#${box.id}`);
    saved.toggleAttribute("checked", box.checked);
    saved.removeAttribute("disabled");
  });
  clone.querySelectorAll(".editable-text").forEach(node => node.setAttribute("contenteditable", "plaintext-only"));
  clone.querySelectorAll(".source-reference").forEach(node => node.setAttribute("hidden", ""));
  clone.querySelectorAll("nav input").forEach(node => node.removeAttribute("checked"));
  clone.querySelector("body").classList.remove("review");
  clone.querySelector("#edit-status").textContent = "已載入儲存的 HTML；修改後請再次儲存。";
  download("<!doctype html>\n" + clone.outerHTML, "text/html;charset=utf-8", "edited-document.html");
  statusElement.textContent = "已匯出 HTML，請與原 assets 資料夾放在同一資料夾後開啟。";
});

document.fonts.ready.then(() => { fitAll(); document.documentElement.dataset.layoutReady = "true"; });
window.addEventListener("beforeprint", fitAll);
