# ExtractAI: Document Intelligence API

A FastAPI service that takes a batch of document URLs, downloads each document safely, classifies it with a **local** vision LLM (Ollama + Qwen3-VL), groups the documents by owner, and extracts structured data with a pipeline chosen for each document type.

All inference runs on your own machine. Documents are never sent to a third-party AI service.

> **Status:** all 12 stages are done and tested. [PROGRESS.md](PROGRESS.md) has every decision and test result.

---

## API

### `POST /document-check`

**Request:** 10 to 50 `http`/`https` URLs of PDF, PNG or JPG/JPEG documents.

```json
{ "documentUrls": ["https://example.com/doc1.pdf", "https://example.com/doc2.png", "... 10 to 50 URLs"] }
```

**Response (`200`):** the documents grouped by owner. `data` is an **object**, not an array.

```json
[
  {
    "ownerName": "John Doe",
    "documents": [
      {
        "documentType": "passport",
        "documentName": "Passport",
        "data": { "passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31" },
        "sourceIndex": 0,
        "error": null
      },
      {
        "documentType": "taxReturn",
        "documentName": "Indian Income Tax Return Acknowledgement",
        "data": { "assessmentYear": 2025, "taxPayerName": "JOHN DOE", "totalIncome": "500000", "taxPaid": "50000", "taxDue": "450000" },
        "sourceIndex": 2,
        "error": null
      }
    ]
  },
  {
    "ownerName": "MARIA DOE",
    "documents": [
      {
        "documentType": "idCard",
        "documentName": "Aadhaar card",
        "data": { "aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01", "address": "123, Main Street, Testcity, Teststate 400001" },
        "sourceIndex": 1,
        "error": null
      }
    ]
  },
  {
    "ownerName": null,
    "documents": [
      { "documentType": "unknown", "documentName": "Grocery receipt", "data": null, "sourceIndex": 3, "error": null },
      { "documentType": "unknown", "documentName": null, "data": null, "sourceIndex": 4,
        "error": "download failed: host 'example.com' returned HTTP 404" }
    ]
  }
]
```

**Error responses:** every error is JSON with a `detail` field.

| Status | When | Body |
|---|---|---|
| `422` | Fewer than 10 or more than 50 URLs, a value that isn't an `http(s)` URL, a missing `documentUrls`, any extra field, or invalid JSON | `{"detail": [{"type": "too_short", "loc": ["body", "documentUrls"], "msg": "..."}]}`. **The submitted values are never echoed back** (FastAPI's default `input`/`ctx` are removed), because URLs can contain access tokens |
| `503` | The model (Ollama) is unreachable or not pulled. This is checked **before** anything is downloaded, with a 5 s timeout | `{"detail": "document model is not available, try again later"}` |
| `500` | An unexpected server error | `{"detail": "internal error"}`. Only the error type is logged, never its message |

Problems with individual documents are **not** request errors: the request returns `200`, and the document carries an `error` (see below).

### Document types and extracted fields

| `documentType` | What it covers | `data` fields |
|---|---|---|
| `passport` | Passport data page | `passportNumber`, `dateOfBirth`, `expiryDate` |
| `idCard` | **Indian Aadhaar only** (card or letter) | `aadharNumber` (spelled this way on purpose), `dateOfBirth`, `address` |
| `taxReturn` | Income tax return or its acknowledgement (ITR / ITR-V) | `assessmentYear` (integer), `taxPayerName`, `totalIncome`, `taxPaid`, `taxDue` |
| `unknown` | Everything else: driving licence, PAN card, voter ID, receipts, letters… | `data` is `null` |

### Response rules

- **No guessing:** every field is nullable, and a value that isn't visible on the document is `null`. For example, the front of an Aadhaar card has no address, so `address` comes back `null`.
- **Formats:** the model copies each value as printed, and the code converts it.
  - Dates become `YYYY-MM-DD`. **Only day-first dates are understood** (`15 MAY 1985`, `01/01/1990`, `23-11-1975`, `05.08.1988`); US month-first dates are not supported.
  - Aadhaar numbers become `1234-5678-9012`, and masked ones `XXXX-XXXX-0123`.
  - Amounts become plain digit strings: `₹ 5,00,000/-` → `"500000"`. `.00` is dropped; other decimals are kept.
  - `assessmentYear` is the first year of the assessment year: `2025-26` → `2025`.
  - A value in an unexpected format is **returned as printed**, never guessed or dropped. An impossible date like `31/02/1990` stays `"31/02/1990"`.
- **Grouping by owner:**
  - Names match regardless of capitals and extra spaces, so `"John Doe"` and `"JOHN DOE"` are one group, shown with the first spelling seen.
  - There is **no fuzzy matching**: `"Jon Doe"` stays a separate person.
  - Groups appear in the order their owner is first seen. Documents with no visible owner, and documents that failed, go in a final `ownerName: null` group.
- **Two fields added** to the brief's original shape:
  - `sourceIndex`: the document's position in `documentUrls`. It matches each result to its URL without repeating URLs, which may contain access tokens.
  - `error`: `null` on success.
- **One bad document never fails the batch.**
  - A document that can't be downloaded, read or classified is returned as `unknown` with an `error`.
  - If only extraction fails, its type, name and owner are kept, with `data: null` and an `error`.
  - Error messages name the host only, never the full URL.
  - The request returns `200` even if every document failed. The one exception is when the model itself is unavailable, which gives `503`.
- **Classification cross-check:** the model sometimes labels any ID card as `idCard`, so the code overrides it. `idCard` becomes `unknown` unless the document's name mentions Aadhaar / UIDAI, and a PAN card labelled `taxReturn` becomes `unknown`.

---

## How it works

```
POST /document-check
  -> validate (10-50 http(s) URLs)
  -> for each URL, concurrently (MAX_CONCURRENT_DOCUMENTS at a time):
       download safely -> PDF pages to PNG (images as they are)
       -> [model lock: MODEL_PARALLEL_REQUESTS]
            classify page 1 -> documentType, documentName, ownerName
            extract with the pipeline for that type (registry lookup)
  -> group by owner -> JSON response
```

- **Pipelines** live in `app/pipelines/`. Each one subclasses `BaseDocumentPipeline` and sets `document_type`, a prompt, a Pydantic schema and `max_pages`.
- **To add a new type** (bank statement, driving licence, payslip…): write a pipeline and add it to `PIPELINE_CLASSES` in `app/pipelines/registry.py`. **The API code doesn't change.** For the classifier to detect the type, also add it to the `DocumentType` enum and the classifier prompt.
- **Ollama** is called directly through its REST API (`/api/chat`) with httpx, with `think: false`, a JSON-schema `format`, `temperature: 0` and `num_ctx`. Only `app/services/ollama.py` knows about Ollama. Every model answer is validated with Pydantic.
- **Shared system prompt:** classification and extraction use the same system prompt, and a document's two model calls always reach Ollama back to back. Ollama can then reuse the work it did on the image in the second call, which cuts the extraction call from about 9 s to about 3 s, and a whole document by about a third. Keep the system prompt shared (`app/services/prompts.py`).

---

## Constraints and limits

### Design rules

- **Stack:** Python 3.11/3.12, FastAPI, Uvicorn, Pydantic v2, httpx, PyMuPDF (`import pymupdf`, not `fitz`), Pillow, python-dotenv, Ollama. **No other frameworks or packages.** For example, settings use a plain dataclass, not `pydantic-settings`, and Ollama is called without the `ollama` Python package.
- **The LLM stays local.** `OLLAMA_HOST` must point at your own machine or network.
- **Configuration comes from `.env`** through `app/config.py`. No secrets are hardcoded.

### Security

- **SSRF protection** (`app/utils/url_safety.py`):
  - Only `http`/`https` URLs are allowed, and URLs with embedded credentials (`user:pass@`) are rejected.
  - The host is resolved, and **every** address must be public. Loopback, private, link-local (including `169.254.169.254` cloud metadata), CGNAT, multicast and IPv4-mapped IPv6 addresses are all blocked.
  - The download then connects to the IP that was checked, sending the real hostname for TLS. That prevents DNS rebinding, and certificates are still verified.
  - Redirects are followed by hand, at most `MAX_REDIRECTS`, and **each hop is checked again**.
  - Proxy environment variables are ignored.
- **Download limits:**
  - The response must be HTTP 200.
  - There's a total time limit (`DOWNLOAD_TIMEOUT_SECONDS`) and a size limit (`MAX_DOWNLOAD_BYTES`), both checked against the `Content-Length` header **and** while streaming, so an oversized download stops early.
  - The `Content-Type` must be `application/pdf`, `image/png` or `image/jpeg`, **and** the file's first bytes must match. `application/octet-stream` is accepted, because storage services like S3 often send it; then the first bytes alone decide.
- **Files:**
  - Each request gets a private temporary folder (mode `0700`) that's **always deleted**: after success, after failure, and when the client disconnects.
  - Files are named by their detected type, not by the URL. Downloaded files are never served.
- **PDFs:**
  - At most `MAX_PDF_PAGES` pages are rendered, and each page is capped at 4000 px on its longest side, so a crafted PDF can't exhaust memory.
  - Password-protected and unreadable PDFs are rejected.
  - MuPDF's own terminal messages are switched off, because they could contain document text.
- **Logging:**
  - Logs never include document contents, extracted values, owner names or model output. They record the host, file type, size, page count, model timing and document index.
  - httpx's request logging is turned down to WARNING, because it would log full URLs and any access tokens in them.

### Performance (MacBook Air M4, 16 GB, `qwen3-vl:8b-instruct`)

- **About 14.5 s per document** (10 documents in 145 s) with the shared-prompt speed-up, compared with about 22 s (216–221 s) without it. Each document needs 2 model calls. A fanless laptop gets about 25% slower under sustained load.
- **A request can take minutes:** 10 documents take about 2–4 minutes and 50 documents 10+ minutes, so clients need a long timeout. There is no overall time limit on a request yet.
- **Ollama 0.14.1 can't run qwen3-vl requests in parallel.** It ignores `OLLAMA_NUM_PARALLEL` for this model and forces `Parallel:1`. `MAX_CONCURRENT_DOCUMENTS` above 1–2 therefore only lengthens Ollama's queue; it still limits load, and helps on machines where Ollama does run in parallel.
- **Only page 1** is used for classification, and the built-in pipelines also send only page 1 (`max_pages = 1`). Each extra page costs up to about 2,000 tokens, so keep `max_pages` at 3 or below, or raise `OLLAMA_NUM_CTX`.
- **`PDF_RENDER_DPI=100`** read every number correctly on the test documents. Scans with small print may need 120–150, which makes each page slower (about 12 s at 100 DPI vs about 31–38 s at 150).

### Known limitations

- Only passports, Aadhaar and tax returns are extracted; everything else is `unknown`.
- Only day-first dates are understood.
- There's no fuzzy name matching, so OCR-level spelling differences create separate owner groups.
- Accuracy has been measured only on the generated **fake** sample documents, not on real-world scans.

---

## Setup (macOS)

### 1. Python environment

```zsh
git clone https://github.com/Mayanksingh2518/ExtractAI.git
cd ExtractAI
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Ollama and the vision model

```zsh
brew install ollama
brew services start ollama
ollama pull qwen3-vl:8b-instruct  # about 6 GB, runs in about 7.4 GB at num_ctx 8192
```

| RAM / VRAM | `OLLAMA_MODEL` | `MAX_CONCURRENT_DOCUMENTS` |
|---|---|---|
| ≤ 8 GB | `qwen3-vl:4b-instruct` | 1 |
| 16 GB (Apple M-series) | `qwen3-vl:8b-instruct` | 2 |
| 32 GB+ | `qwen3-vl:8b-instruct` or larger | benchmark it (see below) |

Use the `-instruct` models. The thinking variant ignores `think: false` and was about 3× slower in testing.

### 3. Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Document Intelligence API` | App title |
| `LOG_LEVEL` | `INFO` | Logging level |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server. Keep it local |
| `OLLAMA_MODEL` | `qwen3-vl:8b-instruct` | Vision model |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Timeout for each model call, including time waiting in Ollama's queue |
| `OLLAMA_NUM_CTX` | `8192` | Context window. Ollama's default of 4096 can cut off images **without an error** |
| `DOWNLOAD_TIMEOUT_SECONDS` | `30` | Total time limit per download |
| `MAX_DOWNLOAD_BYTES` | `20971520` | 20 MB per document |
| `MAX_REDIRECTS` | `3` | Redirects followed per download (each one checked again) |
| `PDF_RENDER_DPI` | `100` | PDF page render resolution |
| `MAX_PDF_PAGES` | `10` | Pages rendered per PDF; the rest are skipped |
| `MAX_CONCURRENT_DOCUMENTS` | `2` | Documents processed at once, **shared by all requests** |
| `MODEL_PARALLEL_REQUESTS` | `1` | Documents in the model at once. Set it to what Ollama really runs in parallel (1 for qwen3-vl on Ollama 0.14) |

## Running

```zsh
source .venv/bin/activate
uvicorn app.main:app --reload
```

- Health check: `curl http://127.0.0.1:8000/` returns `{"status":"ok","service":"document-intelligence-api"}`
- Interactive docs: http://127.0.0.1:8000/docs
- Example (10+ public URLs required):
  ```zsh
  curl -X POST http://127.0.0.1:8000/document-check -H 'content-type: application/json' \
       -d '{"documentUrls": ["https://.../1.pdf", "...", "https://.../10.png"]}'
  ```

Because of SSRF protection, the API **cannot** fetch documents from `localhost` or your local network. That includes a local `python -m http.server`. The end-to-end test works around this with a test-only downloader instead.

## Tests

Every test uses **fake** documents made by `python -m scripts.make_sample_documents`, written to `documents/` (gitignored). Run long tests with `caffeinate -i` so the Mac doesn't sleep.

| Command | Needs Ollama | Checks |
|---|---|---|
| `python -m scripts.test_downloader` | no (internet) | Downloads, SSRF, limits, TLS (24) |
| `python -m scripts.test_pdf` | no | PDF → image conversion (11) |
| `python -m scripts.test_grouping` | no | Group by owner (13) |
| `python -m scripts.test_pipelines` | no | Pipeline base class and registry (20) |
| `python -m scripts.test_concurrency` | no | Concurrency limits, order, failure isolation, cancellation (25) |
| `python -m scripts.test_hardening` | no | 422 without input, 503, safe 500, readiness check (27) |
| `python -m scripts.test_extraction --offline` | no | Formats and schemas (39) |
| `python -m scripts.test_classifier` | yes | Classification of 8 samples + errors (22) |
| `python -m scripts.test_extraction` | yes | + extraction on the samples (47) |
| `python -m scripts.test_document_check` | yes (+ internet) | Full endpoint, 13 URLs (25) |
| `python -m scripts.benchmark_concurrency 1 2 3` | yes | Speed and accuracy per concurrency level |

**Tuning another machine:**
1. Check Ollama's log for `does not currently support parallel requests`.
2. If parallel is supported, set `OLLAMA_NUM_PARALLEL` and `MODEL_PARALLEL_REQUESTS` to the same value.
3. Run the benchmark, with a cool-down between runs on laptops.
4. Keep the fastest setting that still gets 10/10 correct.

## Privacy

These documents contain sensitive personal data. Only process documents you have the right to process, and use made-up documents for testing. The `documents/` folder and `.env` are gitignored.

## Roadmap

- [x] 1. Project skeleton, venv, FastAPI `/` endpoint
- [x] 2. Ollama setup and `app/services/ollama.py`
- [x] 3. `POST /document-check` with 10–50 URL validation
- [x] 4. Safe document downloading (SSRF, limits, allowlist)
- [x] 5. PDF to image conversion
- [x] 6. Classification with the vision model
- [x] 7. Group by owner
- [x] 8. Pipeline architecture (base class + registry)
- [x] 9. Passport, Aadhaar and tax return pipelines
- [x] 10. Connect everything and return the final JSON
- [x] 11. Controlled concurrency + benchmark (+ shared-prompt speed-up)
- [x] 12. Hardening: 422 without the submitted input, 503 when the model is down, safe 500s, logging checks
