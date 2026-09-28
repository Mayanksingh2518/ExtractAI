"use strict";
// ExtractAI web page. Talks to the same-origin API. Everything that comes back from the server
// (including model output) is shown with textContent, never innerHTML, so it can't run as code.

const LIMITS = { minUrls: 10, maxDocs: 50, fileBytes: 20 * 1024 * 1024, uploadBytes: 100 * 1024 * 1024 };
const TYPE_LABELS = { passport: "Passport", idCard: "Aadhaar", taxReturn: "Tax return", panCard: "PAN card", unknown: "Unknown" };
const FIELD_LABELS = {
  passportNumber: "Passport number", dateOfBirth: "Date of birth", expiryDate: "Expiry date",
  aadharNumber: "Aadhaar number", address: "Address",
  assessmentYear: "Assessment year", taxPayerName: "Taxpayer", totalIncome: "Total income", taxPaid: "Tax paid", taxDue: "Tax due",
  panNumber: "PAN", fatherName: "Father's name",
};
const KEY_STORAGE = "extractai-api-key";

const $ = (id) => document.getElementById(id);
const state = { mode: "upload", files: [], controller: null, lastJson: null };

// --- small DOM helper: el("p", {className: "x"}, "text", child) ---
function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children) node.append(child ?? "");
  return node;
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function storage() {
  try { return window.sessionStorage; } catch { return null; }  // blocked storage must not break the page
}

// --- server status ---
async function checkServer() {
  const pill = $("server-status");
  try {
    const response = await fetch("/", { cache: "no-store" });
    const ok = response.ok && (await response.json()).status === "ok";
    pill.textContent = ok ? "Server online" : "Server problem";
    pill.className = `pill ${ok ? "ok" : "bad"}`;
  } catch {
    pill.textContent = "Server offline";
    pill.className = "pill bad";
  }
}

// --- tabs ---
function selectTab(mode) {
  state.mode = mode;
  for (const [name, tab, panel] of [["upload", $("tab-upload"), $("panel-upload")], ["urls", $("tab-urls"), $("panel-urls")]]) {
    const active = name === mode;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
  }
  showError("");
}

// --- files ---
function addFiles(fileList) {
  for (const file of fileList) {
    const duplicate = state.files.some((f) => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified);
    if (!duplicate) state.files.push(file);
  }
  renderFiles();
}

function renderFiles() {
  const list = $("file-list");
  list.replaceChildren();
  state.files.forEach((file, index) => {
    const remove = el("button", { type: "button", textContent: "Remove" });
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.addEventListener("click", () => { state.files.splice(index, 1); renderFiles(); });
    const warn = file.size > LIMITS.fileBytes ? el("span", { className: "warn", textContent: "over 20 MB" }) : "";
    list.append(el("li", {}, el("span", { className: "name", textContent: file.name, title: file.name }),
      el("span", { className: "size", textContent: formatBytes(file.size) }), warn, remove));
  });
}

// --- URLs ---
function parseUrls() {
  return $("url-input").value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function updateUrlCount() {
  const count = parseUrls().length;
  $("url-count").textContent = `${count} URL${count === 1 ? "" : "s"}` +
    (count && (count < LIMITS.minUrls || count > LIMITS.maxDocs) ? ` (need ${LIMITS.minUrls} to ${LIMITS.maxDocs})` : "");
}

// --- validation before sending (the server checks everything again) ---
function validate() {
  if (state.mode === "upload") {
    if (!state.files.length) return "Choose at least one file.";
    if (state.files.length > LIMITS.maxDocs) return `At most ${LIMITS.maxDocs} files per request.`;
    const total = state.files.reduce((sum, f) => sum + f.size, 0);
    if (total > LIMITS.uploadBytes) return `The files add up to ${formatBytes(total)}; the limit is 100 MB per request.`;
    return "";
  }
  const urls = parseUrls();
  if (urls.length < LIMITS.minUrls || urls.length > LIMITS.maxDocs) return `Enter ${LIMITS.minUrls} to ${LIMITS.maxDocs} URLs (you have ${urls.length}).`;
  const bad = urls.find((u) => { try { return !["http:", "https:"].includes(new URL(u).protocol); } catch { return true; } });
  return bad ? `Not an http(s) URL: ${bad}` : "";
}

function showError(message) {
  const box = $("form-error");
  box.textContent = message;
  box.hidden = !message;
}

// --- sending ---
function sourceLabels() {
  return state.mode === "upload" ? state.files.map((f) => f.name) : parseUrls().map((u) => new URL(u).hostname);
}

async function submit() {
  const problem = validate();
  if (problem) return showError(problem);
  showError("");

  const key = $("api-key").value.trim();
  const store = storage();
  if (store && $("remember-key").checked && key) store.setItem(KEY_STORAGE, key);
  else store?.removeItem(KEY_STORAGE);
  const headers = key ? { "X-API-Key": key } : {};
  let url, body;
  if (state.mode === "upload") {
    url = "/document-check/upload";
    body = new FormData();
    for (const file of state.files) body.append("files", file);
  } else {
    url = "/document-check";
    headers["Content-Type"] = "application/json";
    body = JSON.stringify({ documentUrls: parseUrls() });
  }

  const labels = sourceLabels();
  const count = labels.length;
  state.controller = new AbortController();
  setBusy(true, count);
  const started = performance.now();
  try {
    const response = await fetch(url, { method: "POST", headers, body, signal: state.controller.signal });
    const payload = await response.json().catch(() => null);
    if (!response.ok) return showError(describeError(response, payload));
    state.lastJson = payload;
    renderResults(payload, labels, (performance.now() - started) / 1000);
  } catch (err) {
    showError(err.name === "AbortError" ? "Cancelled. The server may still finish the documents already started."
      : "Could not reach the server. Is it running?");
  } finally {
    setBusy(false);
  }
}

function describeError(response, payload) {
  const detail = payload && payload.detail;
  switch (response.status) {
    case 401: return "The server needs a valid API key. Open “API key” below the input and enter it.";
    case 429: return `Too many requests. Try again in ${response.headers.get("Retry-After") || "a few"} seconds.`;
    case 503: return "The AI model isn't available right now (is Ollama running?). Nothing was processed.";
    case 413: return "The upload is too large (100 MB per request).";
    case 422:
      if (Array.isArray(detail)) return "The server rejected the request: " + detail.map((e) => e.msg).join("; ");
      return `The server rejected the request: ${detail || "invalid input"}`;
    default: return `The server returned an error (HTTP ${response.status})${typeof detail === "string" ? `: ${detail}` : ""}.`;
  }
}

let timer = null;
function setBusy(busy, count = 0) {
  $("submit").disabled = busy;
  $("cancel").hidden = !busy;
  clearInterval(timer);
  if (!busy) { $("progress").textContent = ""; return; }
  const start = Date.now();
  const tick = () => {
    const seconds = Math.round((Date.now() - start) / 1000);
    $("progress").textContent = `Processing ${count} document${count === 1 ? "" : "s"}… ${seconds} s ` +
      `(usually 15–20 s per document)`;
  };
  tick();
  timer = setInterval(tick, 1000);
}

// --- results ---
function renderResults(owners, labels, seconds) {
  const docs = owners.flatMap((g) => g.documents);
  const errors = docs.filter((d) => d.error).length;
  const people = owners.filter((g) => g.ownerName).length;
  $("summary").textContent = `${docs.length} document${docs.length === 1 ? "" : "s"}, ${people} owner${people === 1 ? "" : "s"}` +
    `${errors ? `, ${errors} with problems` : ""} · ${seconds.toFixed(0)} s`;

  $("owners").replaceChildren(...owners.map((group) => el("article", { className: "owner" },
    el("h3", { className: group.ownerName ? "" : "none", textContent: group.ownerName ?? "No owner found" }),
    ...group.documents.map((doc) => renderDocument(doc, labels[doc.sourceIndex])))));
  $("results").hidden = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDocument(doc, label) {
  const type = TYPE_LABELS[doc.documentType] ? doc.documentType : "unknown";
  const node = el("div", { className: "doc" },
    el("div", { className: "doc-head" },
      el("span", { className: `badge ${type}`, textContent: TYPE_LABELS[type] }),
      el("span", { className: "doc-name", textContent: doc.documentName ?? "Unnamed document" }),
      el("span", { className: "doc-source", textContent: `#${doc.sourceIndex + 1}${label ? ` · ${label}` : ""}` })));
  if (doc.data) {
    const list = el("dl", { className: "fields" });
    for (const [key, value] of Object.entries(doc.data)) {
      list.append(el("dt", { textContent: FIELD_LABELS[key] ?? key }),
        el("dd", { className: value === null ? "null" : "", textContent: value === null ? "not visible" : String(value) }));
    }
    node.append(list);
  } else if (!doc.error) {
    node.append(el("p", { className: "note", textContent: "No data extracted for this document type." }));
  }
  if (doc.error) node.append(el("p", { className: "error", textContent: doc.error }));
  return node;
}

// --- JSON export ---
function jsonText() { return JSON.stringify(state.lastJson, null, 2); }

async function copyJson() {
  try {
    await navigator.clipboard.writeText(jsonText());
    flash($("copy-json"), "Copied");
  } catch {
    flash($("copy-json"), "Copy failed");
  }
}

function downloadJson() {
  const link = el("a", { href: URL.createObjectURL(new Blob([jsonText()], { type: "application/json" })), download: "extractai-results.json" });
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function flash(button, text) {
  const original = button.textContent;
  button.textContent = text;
  setTimeout(() => { button.textContent = original; }, 1500);
}

// --- wiring ---
document.addEventListener("DOMContentLoaded", () => {
  $("tab-upload").addEventListener("click", () => selectTab("upload"));
  $("tab-urls").addEventListener("click", () => selectTab("urls"));
  for (const tab of [$("tab-upload"), $("tab-urls")]) {
    tab.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const next = state.mode === "upload" ? "urls" : "upload";
      selectTab(next);
      $(`tab-${next}`).focus();
    });
  }

  $("file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  const zone = $("drop-zone");
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragging"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("dragging"); addFiles(e.dataTransfer.files); });

  $("url-input").addEventListener("input", updateUrlCount);
  $("submit").addEventListener("click", submit);
  $("cancel").addEventListener("click", () => state.controller?.abort());
  $("copy-json").addEventListener("click", copyJson);
  $("download-json").addEventListener("click", downloadJson);

  const saved = storage()?.getItem(KEY_STORAGE);
  if (saved) { $("api-key").value = saved; $("remember-key").checked = true; }

  checkServer();
});
