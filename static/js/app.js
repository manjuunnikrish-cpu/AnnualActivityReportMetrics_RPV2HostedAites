"use strict";

// ── Element refs ─────────────────────────────────────────────────────────
const dropZone       = document.getElementById("drop-zone");
const fileInput      = document.getElementById("file-input");
const uploadStatus   = document.getElementById("upload-status");
const datasetSection = document.getElementById("dataset-section");
const datasetMeta    = document.getElementById("dataset-meta");
const previewThead   = document.getElementById("preview-thead");
const previewTbody   = document.getElementById("preview-tbody");
const askSection     = document.getElementById("ask-section");
const questionInput  = document.getElementById("question-input");
const askBtn         = document.getElementById("ask-btn");
const answerSection  = document.getElementById("answer-section");
const answerText     = document.getElementById("answer-text");
const answerTableWrap= document.getElementById("answer-table-wrapper");
const answerThead    = document.getElementById("answer-thead");
const answerTbody    = document.getElementById("answer-tbody");

// ── Drag & drop ──────────────────────────────────────────────────────────
dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

// ── Upload ───────────────────────────────────────────────────────────────
async function uploadFile(file) {
  setStatus("loading", `Uploading "${file.name}"…`);
  datasetSection.classList.add("hidden");
  askSection.classList.add("hidden");
  answerSection.classList.add("hidden");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      setStatus("error", data.error || "Upload failed.");
      return;
    }

    setStatus("success", `✅ Loaded "${file.name}" — ${data.rows.toLocaleString()} rows, ${data.columns.length} columns.`);
    renderDataset(data);
  } catch (err) {
    setStatus("error", "Network error. Please try again.");
  }
}

function setStatus(type, msg) {
  uploadStatus.textContent = msg;
  uploadStatus.className = `status-msg ${type}`;
  uploadStatus.classList.remove("hidden");
}

// ── Render dataset preview ───────────────────────────────────────────────
function renderDataset({ rows, columns, preview }) {
  // Meta tags
  datasetMeta.innerHTML = [
    `<span class="meta-tag">📋 ${rows.toLocaleString()} rows</span>`,
    `<span class="meta-tag">🗂 ${columns.length} columns</span>`,
    ...columns.map(c => `<span class="meta-tag">${escHtml(c)}</span>`),
  ].join("");

  // Preview table header
  previewThead.innerHTML = `<tr>${columns.map(c => `<th>${escHtml(c)}</th>`).join("")}</tr>`;

  // Preview rows
  previewTbody.innerHTML = preview
    .map(row => `<tr>${columns.map(c => `<td title="${escHtml(row[c] ?? "")}">${escHtml(row[c] ?? "")}</td>`).join("")}</tr>`)
    .join("");

  datasetSection.classList.remove("hidden");
  askSection.classList.remove("hidden");
}

// ── Ask question ─────────────────────────────────────────────────────────
askBtn.addEventListener("click", doAsk);
questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") doAsk();
});

// Chip buttons
document.querySelectorAll(".chip").forEach(btn => {
  btn.addEventListener("click", () => {
    questionInput.value = btn.dataset.q;
    doAsk();
  });
});

async function doAsk() {
  const question = questionInput.value.trim();
  if (!question) return;

  answerSection.classList.remove("hidden");
  answerText.textContent = "Thinking…";
  answerTableWrap.classList.add("hidden");
  answerThead.innerHTML = "";
  answerTbody.innerHTML = "";

  try {
    const res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();

    if (!res.ok) {
      answerText.textContent = data.error || "Something went wrong.";
      return;
    }

    answerText.textContent = data.answer;

    if (data.table && data.table.length > 0) {
      const keys = Object.keys(data.table[0]);
      answerThead.innerHTML = `<tr>${keys.map(k => `<th>${escHtml(k)}</th>`).join("")}</tr>`;
      answerTbody.innerHTML = data.table
        .map(row => `<tr>${keys.map(k => `<td title="${escHtml(String(row[k] ?? ""))}">${escHtml(String(row[k] ?? ""))}</td>`).join("")}</tr>`)
        .join("");
      answerTableWrap.classList.remove("hidden");
    }

    answerSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch {
    answerText.textContent = "Network error. Please try again.";
  }
}

// ── Utility ──────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
