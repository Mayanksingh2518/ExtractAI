# ExtractAI: Project Brief and Progress

**This file is the single source of truth for the project.** It records the task, the rules, what has been built and tested, and the exact next step.
On any machine or in any new session, reading this file should be enough to carry on without anyone explaining the context again.

_Last updated: 2026-09-27_

---

## 0. For the AI assistant: how to resume

When the user says **"read PROGRESS.md"**, or starts a new session, do the following in order:

1. **Read this whole file.** Section 5 (the progress checklist) and section 7 (current state) tell you where things stand.
2. **Check the machine** by running the checks in [section 3](#3-resume-checklist-for-a-new-machine). Fix anything missing: venv, packages, `.env`, Ollama, the model, sample documents. If this machine isn't in the Machines table (section 4), add it and choose the model and concurrency from how much RAM it has.
3. **Tell the user in a few lines** what state the machine is in and which step comes next.
4. **Continue from "Next action"** in section 7, following the working agreement in section 1.
5. **After each step, update this file:** tick the checkboxes, record each test and its actual result, add findings, and rewrite section 7. Then offer to commit and push; the user usually wants that at the end of each stage. **Never tick an item that hasn't been tested.**

---

## 1. Working agreement (how the user wants to work)

- The user is **learning**. Build **one step at a time**, and never build the whole project in one go.
- For each step, cover:
  1. which folder or file is being created
  2. the complete code
  3. what the code does
  4. the command to run (macOS / zsh)
  5. the expected output
  6. how to test it
- **The assistant runs the commands and tests itself.** The user asked for this ("do it yourself"). Then show the real output and explain it.
- **Test everything built in every stage**, including the success case, each failure and edge case, and the security checks, and record the real results here. The user asked for this explicitly ("always test everything that you do in each stage").
- Don't treat a step as working until it has been tested. If something fails, fix that step before moving on.
- Keep answers clear and not too long. The user sometimes writes short messages, so read them with this file in mind.
- **Security matters:** use only FAKE sample documents (`scripts/make_sample_documents.py`), never print or log real document contents or full LLM output, and check git history before anything is published.

---

## 2. The task

Build a **Document Intelligence API** in Python that takes a batch of document URLs and returns structured data extracted from them. The documents are passports, Aadhaar cards and tax returns. All AI processing runs on a **local** Ollama vision model, so no document ever goes to a cloud AI service.

### What we want to achieve

One endpoint, `POST /document-check`, that works as follows:

1. **Accepts at least 10 document URLs.** Pydantic rejects requests with fewer.
   ```json
   { "documentUrls": ["https://.../doc1.pdf", "... at least 10"] }
   ```
2. **Downloads** each document with httpx, safely (see the security rules below).
3. **Converts PDFs to page images** with PyMuPDF. PNG, JPG and JPEG files are used as they are. The original file is kept, and each image is processed only once.
4. **Classifies** each document with the local vision model, producing `{documentType, documentName, ownerName}` as JSON that Pydantic has validated.
   - The model must not guess. Any field that isn't visible is `null`, and a document whose type can't be identified gets `documentType: "unknown"`.
   - `DocumentType` enum: `PASSPORT="passport"`, `AADHAAR="idCard"`, `TAX_RETURN="taxReturn"`, `UNKNOWN="unknown"`.
5. **Groups** the documents by `ownerName` (with `dict` or `defaultdict`).
6. **Extracts** type-specific data using a **pipeline registry**, not a long if/elif chain:
   ```python
   PIPELINES = {"passport": PassportPipeline(), "idCard": AadhaarPipeline(), "taxReturn": TaxReturnPipeline()}
   pipeline = PIPELINES.get(document_type)
   if pipeline:
       data = await pipeline.extract(document)
   ```
   - `app/pipelines/base.py`: `class BaseDocumentPipeline(ABC)` with `async def extract(self, image_path)`
   - Adding a new type later (bankStatement, drivingLicence, payslip, W2, 1099, GSTReturn, companyRegistration, utilityBill, …) must **not** require changes to the API code.
7. **Returns** the final JSON. `data` is an **object**, not an array:
   ```json
   [
     {"ownerName": "John Doe", "documents": [
       {"documentType": "taxReturn", "documentName": "2025 Income tax return",
        "data": {"assessmentYear": 2025, "taxPayerName": "John Doe", "totalIncome": "500000", "taxPaid": "50000", "taxDue": "450000"}}]},
     {"ownerName": "Maria Doe", "documents": [
       {"documentType": "idCard", "documentName": "Aadhaar card",
        "data": {"aadharNumber": "1234-5678-9012", "dateOfBirth": "1990-01-01", "address": "123, Main Street, City, State, Country"}},
       {"documentType": "passport", "documentName": "Indian Passport",
        "data": {"passportNumber": "AB123456", "dateOfBirth": "1985-05-15", "expiryDate": "2025-12-31"}}]}
   ]
   ```

### Extraction schemas (every field nullable; extract only what's visible)

| Type | Fields |
|---|---|
| `PassportData` | `passportNumber`, `dateOfBirth`, `expiryDate` (`str \| None`) |
| `AadhaarData` | `aadharNumber` (**spelled exactly this way**), `dateOfBirth`, `address` (`str \| None`) |
| `TaxReturnData` | `assessmentYear` (`int \| None`, **not** "assesmentYear"), `taxPayerName`, `totalIncome`, `taxPaid`, `taxDue` (`str \| None`) |

### Rules and decisions already made (don't reopen these)

- **Stack:** Python 3.11/3.12, FastAPI, Uvicorn, Pydantic v2, httpx, PyMuPDF, Pillow, python-dotenv, Ollama. **No other frameworks or packages.** For example, settings use a plain dataclass, not `pydantic-settings`.
- **Ollama:** call `/api/chat` directly with httpx. **Don't** use the `ollama` Python package. **Only `app/services/ollama.py`** knows about Ollama. Everything else calls `OllamaClient.generate_structured(...)`.
- **Model output:** send `think: false`, a JSON-schema `format` (from `Model.model_json_schema()`), `temperature: 0` and `num_ctx` (default 8192). Use only `message.content`, never log `message.thinking`, and always validate with Pydantic.
- **PyMuPDF:** use `import pymupdf`, **not** `import fitz`.
- **Config** comes from `.env` through `app/config.py` (`get_settings()`). Never hardcode secrets.
- **Security:**
  - The LLM stays local. Never log raw document contents or full LLM responses.
  - Validate URLs and block SSRF: private, loopback and link-local IPs, **checked again after DNS resolution and on every redirect**.
  - Check the HTTP status, and enforce a download timeout, a maximum file size (streamed, so the download stops early), and a content-type plus file-type allowlist (PDF, PNG, JPG/JPEG).
  - Use a private temporary folder per request and always delete it. Never serve downloaded files.
- **Concurrency (Stage 11):** use `asyncio.Semaphore` with a configurable `MAX_CONCURRENT_DOCUMENTS`, and never send 10+ Ollama requests at once. Explain how to benchmark and tune it. Ollama's `OLLAMA_NUM_PARALLEL` matters too.
- **Code style:** clean architecture, type hints, Pydantic models, async endpoints, small focused services, dependency injection where it helps, clear error handling, nothing unnecessarily complex.

---

## 3. Resume checklist for a new machine

Run these from the project root and fix anything that fails. The commands are for macOS / zsh; on Linux use `free -g` for RAM and `curl -fsSL https://ollama.com/install.sh | sh` to install Ollama.

```zsh
# Code
git pull
python3 --version                      # need 3.11 or 3.12
[ -d .venv ] || python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
diff .env .env.example                 # new keys in .env.example? add them to .env

# Hardware (pick the model and concurrency from section 4)
sysctl -n hw.memsize machdep.cpu.brand_string

# Ollama + model
ollama --version || brew install ollama
curl -s localhost:11434/api/tags >/dev/null || brew services start ollama
ollama list                            # is OLLAMA_MODEL from .env pulled?
ollama pull qwen3-vl:8b-instruct       # or the model chosen for this machine

# Fake test data + checks
python -m scripts.make_sample_documents
python -m scripts.test_ollama documents/sample_passport.png
uvicorn app.main:app --reload          # then in another terminal: curl http://127.0.0.1:8000/
```

**Expected:**
- `test_ollama` prints `model available: True` and `{'documentType': 'passport', ..., 'ownerName': 'JOHN DOE'}`.
- `GET /` returns `{"status":"ok","service":"document-intelligence-api"}`.

**Picking the model from RAM:**

| RAM / VRAM | `OLLAMA_MODEL` | Starting `MAX_CONCURRENT_DOCUMENTS` |
|---|---|---|
| ≤ 4 GB GPU | `qwen3-vl:4b-instruct` | 1 |
| 8 GB | `qwen3-vl:4b-instruct` | 1 |
| 16 GB unified (Apple M-series) | `qwen3-vl:8b-instruct` | 2 |
| 32 GB+ | `qwen3-vl:8b-instruct` (or bigger) | 3–4, then benchmark |

---

## 4. Machines

| Machine | Specs | Model | Concurrency | Notes |
|---|---|---|---|---|
| Old laptop | 2 GB GPU | `qwen3-vl:4b` (planned) | 1 | Stage 1 was done here |
| MacBook Air M4 | 16 GB unified, Ollama 0.14.1, Python 3.11.14 | `qwen3-vl:8b-instruct` (`qwen3-vl:8b` also installed) | 2 (to be benchmarked) | Stages 2–3 were done here. Runs 100% on the GPU, about 7.4 GB at `num_ctx` 8192. About 7.7 s per document once loaded |

---

## 5. Progress

Items are ticked only once they have been **built and tested**.

### Stage 1: Project skeleton ✅
- [x] Git repo, folder structure (`app/api`, `schemas`, `services`, `pipelines`, `utils`)
- [x] `requirements.txt`, `.env.example`, `.gitignore` (`.env`, `.venv/`, `__pycache__/`, `documents/` excluded)
- [x] FastAPI app (`app/main.py`) with a `GET /` health check
- [x] **Tested:** all packages import correctly, `GET /` returns `{"status":"ok","service":"document-intelligence-api"}`, and `/docs` loads

### Moving to the MacBook Air M4 ✅
- [x] Repo cloned. Python 3.11.14 venv created and requirements installed
- [x] **Tested:** installed versions are fastapi 0.141.1, pydantic 2.13.5 and pymupdf 1.28.2
- [x] **Tested:** `uvicorn app.main:app` starts, and `GET /` returns 200 with the expected JSON

### Stage 2: Ollama service ✅
- [x] Ollama installed (Homebrew, v0.14.1) and running on `localhost:11434`
- [x] Downloaded `qwen3-vl:8b` (6.1 GB). It has vision support and runs 100% on the GPU
- [x] `scripts/make_sample_documents.py` generates a **fake** passport image at `documents/sample_passport.png` ("Republic of Testland", John Doe, AB1234567)
- [x] **Tested the model directly** by sending the image to `/api/chat` with curl (`stream: false`, `think: false`, `temperature: 0`, JSON-schema `format`). It returned valid JSON with `documentType: "passport"`
- [x] `app/config.py`: a frozen `Settings` dataclass loaded from `.env` and cached with `@lru_cache` in `get_settings()`. Keys: `APP_NAME`, `LOG_LEVEL`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_NUM_CTX`
- [x] `app/services/ollama.py`: `OllamaClient`
  - `generate_structured(response_model, prompt, image_paths, system_prompt=None) -> response_model instance`
  - It builds the request schema with `model_json_schema()`, base64-encodes images in a background thread, uses only `message.content`, and validates with Pydantic
  - Errors raise `OllamaError`, whose messages never contain document data
  - Also has `is_model_available()`, `from_settings()`, `async with` support, and an injectable `http_client`
- [x] `scripts/test_ollama.py` tests the service by hand. It has a temporary `Classification` model; the real one comes in Stage 6
- [x] **Tested the success case:** `python -m scripts.test_ollama documents/sample_passport.png` returns `{'documentType': 'passport', 'documentName': 'PASSPORT', 'ownerName': 'JOHN DOE'}` in about 13 s
- [x] **Tested Ollama being unreachable** (`OLLAMA_HOST=http://localhost:1`): `OllamaError: Could not reach Ollama: ConnectError`
- [x] **Tested a model that isn't installed** (`OLLAMA_MODEL=does-not-exist`): `OllamaError: Ollama returned HTTP 404`
- [x] README written. Code pushed to GitHub and the repo made **public** (https://github.com/Mayanksingh2518/ExtractAI). Git history checked: `.env` and `documents/` were never committed
- [x] `CLAUDE.md` and this `PROGRESS.md` added so work can resume on any machine
- [x] Switched `.env` to `qwen3-vl:8b-instruct`
- [x] **Tested speed against `8b`:** each model was run on 4 different fake passports (names changed so nothing was cached). Both read every name correctly. `8b-instruct` took 7.6–7.9 s per document once loaded (14 s when loading); `8b` took 21.5–27.4 s (26 s when loading). **Instruct is about 3× faster**

#### What the Stage 2 tests showed

| Finding | What we did |
|---|---|
| The first prompt put extra fields into `ownerName` (`"JOHN DOE (Surname: DOE, Passport No.: ...)"`) | Added a system prompt, a `description` on each schema field, and clearer instructions. The result is now `"JOHN DOE"`. Use the same approach for every prompt |
| Ollama's default context window is 4096 tokens, and one small image already used about 1,400 | Set `num_ctx: 8192` (`OLLAMA_NUM_CTX`). Otherwise large PDF pages are cut off **without any error**. Keep this in mind when choosing the PDF render DPI in Stage 5 |
| `qwen3-vl:8b` ignores `think: false` and still writes about 630 characters of reasoning | Still usable, because the reasoning comes back in a separate field. Switching to `qwen3-vl:8b-instruct` for speed |
| Pydantic's enum and `str \| None` schemas (`$defs`, `anyOf`) | Ollama accepts them, so the schemas can be passed in directly |
| Timing on the M4: `8b-instruct` about 7.7 s per document, `8b` about 21–27 s | We use `8b-instruct`. Starting point for tuning in Stage 11 |
| Sending the **same** image twice took only 1.7 s the second time, because Ollama reused its work from the first request | **Benchmarks must use different images each time**, or the numbers come out too fast |

### Stage 3: `POST /document-check` with validation of at least 10 URLs ✅
- [x] `app/schemas/request.py`: `DocumentCheckRequest` with `documentUrls: list[HttpUrl]`, `min_length=10` (`MIN_DOCUMENTS`), `max_length=50` (`MAX_DOCUMENTS`, added so one request can't queue unlimited work), and `extra="forbid"`
- [x] **Tested the schema directly with Pydantic:** 10 URLs are accepted. Each of these is rejected: 9 URLs (`too_short`), 60 URLs (`too_long`), `"not-a-url"` (`url_parsing`), `ftp://` (`url_scheme`), a missing `documentUrls` (`missing`), and an extra field `foo` (`extra_forbidden`)
- [x] `app/api/document_check.py`: an `APIRouter` (tag `documents`) with `POST /document-check`, which takes `DocumentCheckRequest` and for now returns `{"received": <number of URLs>}`. Registered in `app/main.py` with `app.include_router(...)`
- [x] **Tested over HTTP with curl against uvicorn:** 10 URLs → 200 `{"received":10}`; 9 URLs → 422 `too_short`; `"not-a-url"` → 422 `url_parsing`; `{}` → 422 `missing`; a body that isn't JSON → 422 `json_invalid`. `/docs` → 200, and OpenAPI lists `/document-check` and `/`
- [x] **Finding:** FastAPI's default 422 response repeats the submitted `input` (the URLs) back to the caller. Signed document URLs can contain access tokens, so **Stage 12 must add a validation-error handler that removes `input` from 422 responses** (added to Stage 12 below)

### Stage 4: Downloading documents ✅
- [x] Settings in `app/config.py`, `.env.example` and `.env`: `DOWNLOAD_TIMEOUT_SECONDS=30`, `MAX_DOWNLOAD_BYTES=20971520` (20 MB), `MAX_REDIRECTS=3`
- [x] `app/utils/url_safety.py`: `resolve_public_ip(url)`
  - Allows only `http`/`https`, and rejects URLs with embedded credentials
  - Resolves the host, and requires **every** address to be public: `ip.is_global` and not multicast, with IPv4-mapped IPv6 unwrapped first
  - Returns the checked IP, so the download connects to it without a second DNS lookup (this blocks DNS rebinding)
- [x] `app/utils/workspace.py`: `request_workspace()` context manager, giving a private temporary folder (`mkdtemp`, mode 0700) that's always deleted
- [x] `app/services/downloader.py`: `DocumentDownloader.download(url, dest_dir, name) -> DownloadedDocument(url, path, kind, size_bytes)`
  - Connects to the checked IP, sending the real hostname in the `Host` header and as the TLS SNI, so certificates are still verified against the hostname
  - `follow_redirects=False`: redirects are followed by hand (at most `MAX_REDIRECTS`), and **each hop goes through the SSRF check again**
  - `trust_env=False`, so proxy environment variables can't bypass the pinning
  - Status must be 200. Downloads are capped by `Content-Length` **and** by counting bytes while streaming (it stops early). `asyncio.timeout` caps the **total** time, not just each read
  - Allowlist: `Content-Type` must be `application/pdf`, `image/png` or `image/jpeg`, **and** the first bytes must match (`%PDF-`, the PNG header, `FFD8FF`). **Decision:** `application/octet-stream` is accepted (S3 and similar storage commonly send it); for those the file's first bytes alone decide
  - Files are saved as `<name>.<pdf|png|jpg>` based on the detected type, not the URL. Partial files are deleted on any failure
  - Errors raise `DownloadError`. Messages contain the host only, never the full URL (which may hold tokens). The log line records host, kind and size
- [x] **Tested `url_safety` (22 cases), all correct:**
  - Allowed: `example.com`, `w3.org`
  - Blocked: `127.0.0.1`, `localhost`, `10.x`, `192.168.x`, `172.16.x`, `169.254.169.254`, `0.0.0.0`, `100.64.x` (CGNAT), `224.0.0.1`, `[::1]`, `[::ffff:127.0.0.1]`, `[fe80::1]`, `[fd00::1]`, decimal `2130706433`, `127.0.0.1.nip.io`, `10.0.0.1.nip.io`, `ftp://`, `file://`, `user:pass@`, an unresolvable host
- [x] **Tested `workspace`:** mode `0o700`; deleted after a normal exit and after an exception
- [x] **Tested the downloader with `python -m scripts.test_downloader`: 24/24 pass** (real servers plus mock responses)
  - Success: PDF (w3.org), PNG, JPEG, a redirect to a public PNG, and `octet-stream` with PDF bytes
  - Rejected: HTTP 404, HTTP 500, `text/html`, `application/json`, `image/png` whose body was JSON, a redirect to `127.0.0.1:11434`, a redirect to `169.254.169.254`, a redirect to `10.0.0.1.nip.io`, 5 redirects (max 3), `localhost:11434` directly, size limit by Content-Length, size limit while streaming (chunked), a slow server hitting the total timeout (3 s), an expired TLS certificate, a TLS certificate for the wrong host, octet-stream with random bytes, `application/pdf` whose body was PNG, and a missing Content-Type
  - Pinning: the request went to the checked IP (`172.66.147.243`) with `Host: example.com` and SNI `example.com`
  - No partial files were left after failures, and no `extractai-*` temporary folders were left on disk

### Stage 5: PDF to image conversion ✅
- [x] Settings: `PDF_RENDER_DPI=100` and `MAX_PDF_PAGES=10` (config, `.env.example`, `.env`)
- [x] `app/utils/pdf.py`: `to_page_images(file_path, out_dir, dpi, max_pages) -> list[Path]`
  - PDF: renders each page to `<name>_page<N>.png` using `import pymupdf`, inside `asyncio.to_thread` because it's CPU work. The original PDF is kept. At most `MAX_PDF_PAGES` pages are rendered, and the rest are skipped (logged as a count only)
  - PNG/JPEG: returned **as is**, with no re-encoding and no copy (so each image is processed only once)
  - Safety: pages are limited to 4000 px on the longest side (`MAX_RENDER_SIDE_PX`; the DPI is lowered for huge pages), so a PDF can't run the machine out of memory
  - Errors raise `PdfConversionError`: not a readable PDF, password-protected, no pages, a page that can't be rendered, or an unsupported file type
  - MuPDF's own messages to the terminal are turned off (`mupdf_display_errors/warnings(False)`). They bypass logging and could include document text
- [x] `scripts/make_sample_documents.py` now also makes `sample_passport_scan.pdf` (1-page scan-style PDF) and `sample_tax_return.pdf` (3-page fake ITR: AY 2025-26, JOHN DOE, income 5,00,000, taxes paid 50,000, tax due 4,50,000)
- [x] **Tested with `python -m scripts.test_pdf`: 11/11 pass**
  - 1-page PDF → 1 image; 3-page → 3; 12 pages with a limit of 10 → 10
  - PNG and JPEG returned as the **same file**, unchanged (SHA-256 checked)
  - A 200×200 inch page was limited to 4000×4000
  - An owner-password-only PDF opens. A user-password PDF, garbage named `.pdf`, and `.txt` are each rejected with a clear error
  - A truncated PDF is repaired by MuPDF (3 pages)
  - The original file is always kept and unchanged
- [x] **Tested rendered pages with the model** (`scripts/test_ollama.py`): the scanned passport PDF gave passport / JOHN DOE; tax return page 1 gave taxReturn / JOHN DOE; tax return page 2 (no name on it) gave `ownerName: None`, which is correct (no guessing)
- [x] Regression check: `test_downloader` 24/24, `test_ollama` OK

#### What the Stage 5 tests showed

| Finding | What we did |
|---|---|
| Ollama shrinks big images itself. Tokens ≈ pixels/1000 up to about 2 MP, then **stop at about 2,000 tokens** (a 12 MP photo cost the same as a 2 MP one) | One page always fits in `num_ctx` 8192. Sending **several pages in one call** adds up to 2,000 tokens each, so keep multi-page calls to 3 pages or fewer, or raise `OLLAMA_NUM_CTX` |
| Time grows with pixels. A page took 7 s at 72 DPI, 12 s at 100, 19 s at 120, and 31–38 s at 150. All were classified correctly | **Default is `PDF_RENDER_DPI=100`**. **Check again in Stage 9**, when we extract small print (Aadhaar numbers, tax amounts). If numbers are misread, try 120–150 |
| Large PNG/JPEG photos pass through unchanged, and Ollama shrinks them to about 2 MP, which takes about 30 s | Consider this in Stage 11 (for example, shrinking very large photos once). Not done now, because of the "don't process images more than once" rule |

### Stage 6: Classification ✅
- [x] `app/schemas/classification.py`: the `DocumentType` enum and `Classification`
  - **Field order is `documentName`, `documentType`, `ownerName` on purpose.** The model fills in fields in schema order, so naming the document first grounds the type choice. This fixed the driving licence being classified as `idCard`
  - A `field_validator` tidies spacing and turns `""`, `"null"`, `"none"`, `"n/a"` and `"unknown"` into `None`
  - **Tested:** normal input, extra spaces, empty or `"null"` strings becoming `None`, a real `null`, a bad enum value (rejected), a missing field (rejected)
- [x] `app/services/classifier.py`: `DocumentClassifier(ollama, max_pages=1).classify(page_images) -> Classification`
  - **Decision:** only **page 1** is sent. Page 1 identifies nearly every document, and each extra page costs up to about 2,000 tokens
  - **Decision:** if Ollama fails, it raises `ClassificationError` (messages are safe to log). Stage 10/12 will turn that into a per-document failure, so one bad document doesn't fail the whole batch
  - `SYSTEM_PROMPT` and `CLASSIFY_PROMPT` define each type and say that other ID cards are `unknown`. `ownerName` must be the holder only: no relatives (S/O, D/O), no authority
- [x] `scripts/test_ollama.py` now imports the real schema and prompts (no duplicate copies)
- [x] New fake samples in `scripts/make_sample_documents.py`: `sample_aadhaar.png` (MARIA DOE, 2345 6789 0123, DOB 01/01/1990, address), `sample_driving_licence.png` (ALEX KUMAR), `sample_pan_card.png` (SARA LEE, FGHIJ5678K), `sample_receipt.png`, `sample_passport_no_name.png` (name fields blank)
- [x] `scripts/test_classifier.py`: 8 sample cases plus 2 error cases
- [x] **Name cross-check** in `app/services/classifier.py`: `check_type_against_name(result)` runs after every model call. It uses the model's own `documentName`, which is reliably correct, to overrule the enum choice, which is not:
  - `idCard` whose name doesn't contain `aadhaar` / `aadhar` / `uidai` (casefolded) → `unknown`. A `null` name also gives `unknown`, since Aadhaar can't be confirmed (no guessing)
  - `taxReturn` whose name contains `permanent account number` / `pan card` → `unknown` (the PAN card's earlier mistake)
  - **Decision: passport has no check.** Real passports are titled in many ways ("Travel Document", "Pasaporte", …), so a keyword check would cause false `unknown`s
- [x] **Tested with `caffeinate -i python -u -m scripts.test_classifier`: 22/22 on two runs in a row**
  - 12 offline cross-check cases (no Ollama): Aadhaar / AADHAR / UIDAI letter stay `idCard`; PAN, voter ID and a `null` name as `idCard` → `unknown`; "PAN card" and "Permanent Account Number Card" as `taxReturn` → `unknown`; "ITR-V Acknowledgement" and "2025 Income tax return" stay `taxReturn`; "Travel Document" stays `passport`; `unknown` stays `unknown`. `documentName` and `ownerName` are never changed
  - 8 model cases, all PASS both runs: passport PNG → passport / John Doe; passport scan PDF → passport / John Doe; Aadhaar → idCard / MARIA DOE; tax return PDF → taxReturn / JOHN DOE; driving licence → unknown; **PAN card → unknown** (name "Permanent Account Number Card"); receipt → unknown / owner None; passport with no name → passport / owner **None**
  - 2 error cases: Ollama unreachable → `ClassificationError`; no pages → `ClassificationError`
  - Speed: about 8–14 s per document (20 s for the first one while the model loads)

#### What the Stage 6 tests showed

| Finding | What we did / will do |
|---|---|
| The model fills in fields in schema order; choosing the type before naming the document gave driving licence → `idCard` | Moved `documentName` first. The driving licence now comes back `unknown` |
| The model reads the value "idCard" as *any* ID card; the prompt alone doesn't fix the PAN card | Added `check_type_against_name`: the model's `documentName` overrules its type choice. PAN card is now `unknown` on every run |
| `ownerName` capitalisation varies between runs ("John Doe" / "JOHN DOE") | **Stage 7 must group with a normalised key** (casefold, collapse spaces) but show a readable name |
| **The Mac went to idle sleep during a long test run on battery**, causing a 9.5-minute gap (confirmed with `pmset -g log`) | Run long tests and benchmarks with **`caffeinate -i`**, and use `python -u` so output appears straight away |
| Speed at `PDF_RENDER_DPI=100`: about 9–17 s per document | Tune in Stage 11 |

### Stage 7: Group by owner ⬜
- [ ] Group documents by `ownerName` with `defaultdict(list)`
- [ ] Test: documents from 2 owners, plus ones with a `null` owner

### Stage 8: Pipeline architecture ⬜
- [ ] `app/pipelines/base.py`: `BaseDocumentPipeline(ABC)` with `async def extract(self, image_path)`
- [ ] `app/pipelines/registry.py`: the `PIPELINES` dict and a lookup helper
- [ ] Test: a type with no pipeline doesn't crash and gets `data: null` or `{}`. Decide which and record it here

### Stage 9: Passport, Aadhaar and tax return pipelines ⬜
- [ ] `PassportData`, `AadhaarData`, `TaxReturnData` schemas (watch the exact field spellings)
- [ ] `app/pipelines/passport.py`, `aadhaar.py`, `tax_return.py`
- [ ] Add fake Aadhaar and tax return samples to `scripts/make_sample_documents.py`
- [ ] Test each pipeline on its sample. Missing fields should come back as `null`

### Stage 10: Connect everything ⬜
- [ ] Endpoint runs the full flow: download, convert, classify, group, extract, respond. `app/schemas/response.py` holds the response models
- [ ] Test with 10+ sample URLs (served locally or from a test host; note that SSRF protection blocks localhost, so plan for that): the response matches the target JSON shape

### Stage 11: Concurrency ⬜
- [ ] `asyncio.Semaphore(MAX_CONCURRENT_DOCUMENTS)`, set from `.env`
- [ ] Benchmark 10 documents at concurrency 1, 2 and 3, together with `OLLAMA_NUM_PARALLEL`, and watch memory with `ollama ps`
- [ ] Record the best value for each machine in section 4

### Stage 12: Hardening ⬜
- [ ] Consistent error responses. If one document fails, the rest of the batch still completes
- [ ] Custom `RequestValidationError` handler: keep `type`, `loc` and `msg`, and **remove `input`**, so URLs and tokens aren't repeated back (found in Stage 3)
- [ ] Temporary files cleaned up on every path
- [ ] Structured logging with no personal data
- [ ] Final README pass

---

## 6. File map (what exists now)

```
app/main.py                    FastAPI app + GET /
app/config.py                  Settings from .env (get_settings)
app/services/ollama.py         OllamaClient.generate_structured -> validated Pydantic model
app/schemas/request.py         DocumentCheckRequest (10-50 http(s) URLs)
app/api/document_check.py      POST /document-check (placeholder: returns {"received": n})
app/utils/url_safety.py        SSRF check: resolve_public_ip(url)
app/utils/workspace.py         request_workspace(): private temp dir, always deleted
app/services/downloader.py     DocumentDownloader.download(url, dest_dir, name)
scripts/test_downloader.py     24 live + mock download/security checks
app/utils/pdf.py               to_page_images(): PDF -> PNG pages, images pass through
scripts/test_pdf.py            11 conversion checks
app/schemas/classification.py  DocumentType enum + Classification (documentName first!)
app/services/classifier.py     DocumentClassifier.classify(page_images) -> Classification (+ check_type_against_name)
scripts/test_classifier.py     12 offline cross-checks + 8 sample + 2 error classification checks
app/{api,schemas,pipelines,utils}/__init__.py   empty, filled in by later stages
scripts/make_sample_documents.py   writes fake passport (png, scan pdf, no-name), tax return pdf, aadhaar, driving licence, PAN card, receipt into documents/
scripts/test_ollama.py         manual check of the Ollama service
README.md                      public project README
CLAUDE.md                      tells the AI assistant to start from this file
PROGRESS.md                    this file
```

---

## 7. Current state and next action

**Status:** Stages 1–6 are done. Classification passes 22/22 on two runs in a row, with the PAN card fixed by the name cross-check. Nothing is connected to the endpoint yet; that's Stage 10. The model is `qwen3-vl:8b-instruct`, with `PDF_RENDER_DPI=100`.

**Next action:**
1. **Stage 7: group by owner.** Write a small grouping helper (for example `app/services/grouping.py`) using `defaultdict(list)`:
   - Group with a **normalised key** (casefold, collapse spaces), because the model returns "John Doe" and "JOHN DOE" for the same person. Show a readable name (for example the first one seen, or title case). Decide which and record it.
   - Documents with `ownerName = null` go in their own group. Decide the label (for example `ownerName: null`) and record it.
   - Test with no Ollama: 2 owners with mixed capitalisation and spacing, plus `null`-owner documents, plus an empty input.
2. Waiting on the user: remove `qwen3-vl:8b` (`ollama rm qwen3-vl:8b`) to free 6 GB?
