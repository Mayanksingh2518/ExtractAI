# ExtractAI: Project Brief and Progress

**This file is the single source of truth for the project.** It records the task, the rules, what has been built and tested, and the exact next step.
On any machine or in any new session, reading this file should be enough to carry on without anyone explaining the context again.

_Last updated: 2026-09-28 (Stage 20 done; Google Sheets optional, needs the user's Google sign-in)_

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
pip install -r requirements-dev.txt     # app packages + pytest (dev only)
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
python -m scripts.make_sample_documents && python -m scripts.make_realistic_documents
python -m scripts.check_ollama documents/sample_passport.png
pytest                                 # fast offline tests (~15 s); `caffeinate -i pytest -m ""` runs everything
uvicorn app.main:app --reload          # then in another terminal: curl http://127.0.0.1:8000/
```

**Expected:**
- `check_ollama` prints `model available: True` and `{'documentType': 'passport', ..., 'ownerName': 'JOHN DOE'}`.
- `pytest` ends with `... passed, ... deselected` and no failures.
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
| MacBook Air M4 | 16 GB unified, **Ollama 0.34.4** (upgraded from 0.14.1 on 2026-09-28), Python 3.11.14 | `qwen3-vl:8b-instruct` | `MAX_CONCURRENT_DOCUMENTS=2`, `MODEL_PARALLEL_REQUESTS=1` (qwen3-vl still runs one request at a time on 0.34.4) | 0.14.1: about **14.5 s per document** rested (145 s / 10). 0.34.4: about 20 s per document (198 s, 205 s), cause not isolated (see Stage 16). Runs 100% on the GPU: 5.9 GB on 0.34.4 (7.4 GB on 0.14.1) at `num_ctx` 8192 |

---

## 5. Progress

Items are ticked only once they have been **built and tested**.

> Stages 1–16 were tested with the `scripts/test_*.py` scripts named below. **Since Stage 17 those checks live in `tests/` and run with pytest**; the old script commands no longer exist.

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

### Stage 7: Group by owner ✅
- [x] `app/services/grouping.py`: `group_by_owner(items, owner_of) -> list[OwnerGroup]`, using `defaultdict(list)`. `OwnerGroup(ownerName, documents)`
  - It's generic: it takes any item plus a function that returns its owner name, so Stage 10 can pass whatever document objects it builds
  - **Decision: the grouping key is `owner_key(name)`,** which casefolds and collapses spaces, so "John Doe", "JOHN DOE" and "john  doe" are one person. **No fuzzy matching:** "Jon Doe" stays separate, because merging people by guesswork is worse than keeping them apart
  - **Decision: the displayed name is the first spelling seen**, with spaces tidied but otherwise unchanged. Title-casing would break names like "McDonald" or "D'Souza"
  - **Decision: documents with no owner** (`null`, `""` or blank) go in one group with `ownerName: null`, **placed last**. The other groups keep the order in which their owner is first seen
- [x] **Tested with `python -m scripts.test_grouping`: 13/13 pass** (no Ollama)
  - 2 owners in mixed spellings plus 2 `null` documents → `["John Doe", "MARIA DOE", None]`; each group keeps input order; every document appears exactly once; the same objects are returned, unchanged
  - Empty input → `[]`; only `null` owners → a single `null` group; no `null` owners → no `null` group
  - "John Doe" / "Jon Doe" / "John Doe Jr" → 3 separate groups
  - `"  "` and `""` → `null` group; `" Sara  Lee "` + `"SARA LEE"` → one group displayed as "Sara Lee"
  - "José Núñez" + "JOSÉ NÚÑEZ" → one group
- [x] **Tested with the real model:** classified all 8 samples and grouped them. Passport PNG ("John Doe"), passport scan PDF ("John Doe") and tax return ("JOHN DOE") → **one group, "John Doe"**. Aadhaar → MARIA DOE; driving licence → ALEX KUMAR; PAN → Sara Lee; passport with no name and receipt → `null` group, last
- **Open for Stage 10:** `unknown` documents that have an owner (driving licence, PAN) currently get their own groups. Decide whether the response includes them (probably yes, with `data: null`) and record the decision

### Stage 8: Pipeline architecture ✅
- [x] `app/pipelines/base.py`: `BaseDocumentPipeline(ABC)` with `async def extract(self, page_images: list[Path]) -> BaseModel`
  - **Decision: `extract` takes the list of page images, not a single `image_path`.** A tax return's totals can be on page 2 or 3. Each pipeline sets `max_pages` (default 1; keep it at 3 or fewer, per the Stage 5 token finding)
  - The `OllamaClient` is passed in through the constructor (dependency injection). `document_type` is a class attribute, and `__init_subclass__` raises `TypeError` if a pipeline forgets it
  - Helper `_generate(schema, prompt, page_images)`: sends the first `max_pages` pages with a shared no-guessing `SYSTEM_PROMPT` and raises `ExtractionError` on Ollama failure or no pages (messages are safe to log). Stage 9 pipelines are just a schema, a prompt and a one-line `extract`
- [x] `app/pipelines/registry.py`: `PipelineRegistry` wraps the `{document_type: pipeline}` dict. It has `get(type)` (accepts the enum or a string), `extract(type, pages)`, `types`, and `build(ollama)` from `PIPELINE_CLASSES`
  - **To add a type:** write a subclass and add it to `PIPELINE_CLASSES`. The API doesn't change. (For the classifier to detect a new type, the `DocumentType` enum and prompt also need it)
  - Keys are plain strings, so a pipeline can be registered for a type the enum doesn't have yet
  - Duplicate `document_type` → `ValueError`
  - `PIPELINE_CLASSES` is empty until Stage 9
- [x] **Decision: a type with no pipeline (e.g. `unknown`) gets `data: null`, not `{}`.** `null` means "not extracted"; `{}` would look like "extracted, nothing found". `registry.extract` returns `None` and makes no model call
- [x] **Tested with `python -m scripts.test_pipelines`: 20/20 pass** (fake pipelines + a fake Ollama client that records calls)
  - Lookup by enum and by string; `unknown` and an unregistered `idCard` → `None`; `types` listed
  - Extract returns the validated model; `max_pages=1` sends only page 1; the shared system prompt is sent
  - `unknown` → `None` **with no model call**
  - A new `bankStatement` pipeline works through the registry with no other changes; its `max_pages=3` sends pages 1–3; 2 pages with `max_pages=3` sends 2
  - Ollama down → `ExtractionError: passport extraction failed: Could not reach Ollama: ConnectError`; no pages → `ExtractionError`
  - The base class can't be instantiated; a subclass without `extract()` or without `document_type` → `TypeError`; duplicate type → `ValueError`
  - `PipelineRegistry.build()` works with the (still empty) real list

### Stage 9: Passport, Aadhaar and tax return pipelines ✅
- [x] **Decision: the model copies values exactly as printed, and code converts them** (`app/utils/normalize.py`). Values that don't match a known format are **kept as printed**, never guessed or dropped:
  - `to_iso_date`: day-first formats (`15 MAY 1985`, `01/01/1990`, `23-11-1975`, `05.08.1988`, `15-Sep-1985`, ISO) → `YYYY-MM-DD`. **US month-first dates are not supported** (Indian documents and passports are day-first). An impossible date like `31/02/1990` is kept as printed
  - `to_aadhaar_number`: 12 digits with or without spaces or dashes → `1234-5678-9012`; masked `XXXX XXXX 0123` → `XXXX-XXXX-0123`
  - `to_amount`: removes `₹`, `Rs.`, `INR`, `/-`, commas and spaces (Indian `5,00,000` → `500000`); `.00` dropped, other decimals kept (`1234.50`); `Nil` kept as printed
  - `clean_text`: collapses spaces; `""`, `null`, `none`, `n/a`, `na`, `-`, `not visible` → `None`
- [x] `app/schemas/extraction.py`: `PassportData`, `AadhaarData` (**`aadharNumber`**), `TaxReturnData` (**`assessmentYear: int | None`**). Every field is nullable, with a `description` telling the model to copy the value as printed, and validators that call the normalisers
  - **Exception:** `assessmentYear` is an integer in the schema Ollama receives, so the model itself converts "AY 2025-26" → 2025 (the prompt says: first year, not the financial year). Out-of-range values (not 1900–2100) → `None`, treated as a misread
  - Passport numbers: spaces removed, uppercased
- [x] `app/pipelines/passport.py`, `aadhaar.py`, `tax_return.py`: each is a prompt plus a one-line `extract` using `_generate`. All three are in `PIPELINE_CLASSES`
  - **Decision: tax return `max_pages = 1`.** The ITR-V acknowledgement has every field on page 1; raise it to 2–3 for full ITR forms
- [x] New fake sample `sample_aadhaar_front.png` (RAVI SHARMA, 9876 5432 1098, DOB 23/11/1975, **no address**, like the front of a real Aadhaar card)
- [x] **Tested with `caffeinate -i python -u -m scripts.test_extraction`: 47/47 on two runs in a row**
  - Part A (offline, `--offline`), 39 checks: 13 dates, 8 Aadhaar numbers, 10 amounts, the three schemas (exact field names and normalised output), out-of-range year → `None`, the model schema asks for an integer year, the registry has `passport`/`idCard`/`taxReturn`, every key is a real `DocumentType`, `unknown` has no pipeline
  - Part B (model), 8 checks, exact values:
    - passport PNG and scan PDF → `AB1234567`, `1985-05-15`, `2030-12-31`
    - passport with no name → `CD7654321`, `1979-02-02`, `2029-01-01`
    - Aadhaar → `2345-6789-0123`, `1990-01-01`, full address
    - **Aadhaar front → `address: null`** (missing field → null ✅)
    - tax return → `2025`, `JOHN DOE`, `500000`, `50000`, `450000`
    - **tax return page 2 only (salary schedule, no totals) → all `null`**. The model did not use "Salary: 5,00,000" as total income (no guessing ✅)
    - Ollama unreachable → `ExtractionError`
  - Speed: about 8–16 s per document
  - Regression: `test_pipelines` 20/20, `test_grouping` 13/13
- [x] **`PDF_RENDER_DPI=100` re-check:** every number was read correctly. **Caveat:** the fake samples use large fonts (26–32 px, 13 pt in the PDF). Real scans with small print may need 120–150. Test this when real-looking samples are available
- [x] **`qwen3-vl:8b` comparison: not needed**, since `8b-instruct` got every value right

### Stage 10: Connect everything ✅
- [x] `app/schemas/response.py`: `DocumentResult {documentType, documentName, data, sourceIndex, error}` and `OwnerResult {ownerName, documents}`. The route returns `list[OwnerResult]`
- [x] `app/services/document_processor.py`: `DocumentProcessor(downloader, classifier, registry, settings).process(urls)`
  - Per document: download → `to_page_images` → classify → `registry.extract`, each document in its own subfolder of one `request_workspace()`. Then `group_by_owner`
  - One document at a time for now (Stage 11 adds concurrency)
- [x] `app/main.py`: a `lifespan` creates the `OllamaClient`, `DocumentDownloader`, classifier, registry and processor **once at startup** (shared connection pools) and closes them at shutdown. `logging.basicConfig` uses `LOG_LEVEL`
- [x] `app/api/document_check.py`: `POST /document-check` (`response_model=list[OwnerResult]`) gets the processor through `Depends(get_processor)`, which tests replace with `app.dependency_overrides`
- **Decisions:**
  - **One bad document never fails the batch.** It stays in the response with an `error` message that's safe to show (host only, never the full URL). If download, reading or classification fails → `documentType: "unknown"`, `documentName: null`, `data: null`, in the `null`-owner group. If only extraction fails → type, name and owner are kept, `data: null`, `error` set. An unexpected exception (a bug) → `error: "internal error"`, and only the exception **type** is logged, never its message
  - **`unknown` documents are included**, with `data: null` and `error: null` (e.g. the driving licence and PAN card get their own owner groups)
  - **Two fields added** to each document beyond the brief's shape: `error` (`null` on success), and `sourceIndex` (position in `documentUrls`) so callers can match results to their URLs without the response repeating URLs, which may hold tokens
  - The request returns **200 even if every document failed** (e.g. Ollama down), with an error on each document. Stage 12 may revisit this (for example 503 when Ollama is unreachable)
  - **Testing without weakening SSRF protection:** `SampleDownloader` lives **only in `scripts/test_document_check.py`**. It serves `documents/` for the fake host `samples.test` and sends every other URL through the real `DocumentDownloader`. No test switch exists in `app/`
- [x] **Tested with `caffeinate -i python -u -m scripts.test_document_check`: 25/25 on two runs in a row** (in-process via `httpx.ASGITransport`, real classifier, pipelines and model)
  - 13 URLs → 200 in 180 s / 222 s. Groups: `["John Doe", "MARIA DOE", "RAVI SHARMA", "ALEX KUMAR", "Sara Lee", null]`; John Doe = passport PNG + tax return ("JOHN DOE") + passport PDF; `sourceIndex` 0–12 each exactly once
  - All 9 samples have the exact expected type, owner and data (Aadhaar front → `address: null`; no-name passport → `null` owner but data extracted)
  - Real SSRF block (`127.0.0.1:11434`) → `download failed: blocked URL: ...`; 404 → `download failed: host 'samples.test' returned HTTP 404`; fake PDF → `could not read document: file is not a readable PDF`; real w3.org PDF → `unknown` ("Dummy PDF file")
  - No full URL in the response; the brief's field names are present; 9 URLs → 422; the temporary workspace is deleted
  - Extraction failure → type and owner kept, `data: null`, error set; a type with no pipeline → `data: null`, **no** error; Ollama down → every document in the `null` group with `classification failed: Could not reach Ollama`; a `RuntimeError` holding "secret" text → `internal error`, and "secret" appears nowhere in the response
- [x] **Tested the real server** (`uvicorn` + `curl`, real downloader, 10 URLs): 200 in 20.5 s. Two w3.org PDFs (with `?token=SECRET123`) → `unknown` "Dummy PDF file". Blocked: `127.0.0.1`, `169.254.169.254`, `10.0.0.1.nip.io`, `localhost`, `user:pw@`. Also httpbin 404, `text/html` not allowed, example.com 404. **`SECRET123` and the URL path appear 0 times in the server log**, and no `extractai-*` folders were left
- [x] Regression: `test_extraction --offline` 39/39, `test_pipelines` 20/20, `test_grouping` 13/13

#### What the Stage 10 tests showed

| Finding | What we did |
|---|---|
| **httpx logs every request's full URL at INFO** (`GET https://104.18.23.19/WAI/.../dummy.pdf`), so signed-URL tokens would reach the logs | `app/main.py` sets the `httpx` and `httpcore` loggers to WARNING. Checked: the token and path appear 0 times in the log |
| 13 documents one at a time take **180–222 s** (about 14–17 s each: 2 model calls per document) | Clients need a long timeout. **Stage 11** (concurrency) is the fix |
| A repeated URL was classified in 1.7 s (Ollama reused its cached work) | Same as Stage 2: benchmarks must use different images |
| `TestClient` runs the app on a separate event loop, which can't share our async Ollama client | The test uses `httpx.ASGITransport` on the same loop instead |

### Stage 11: Concurrency ✅
- [x] `MAX_CONCURRENT_DOCUMENTS` (default 2; values below 1 become 1) in config, `.env.example` and `.env`
- [x] `DocumentProcessor.process`: `asyncio.gather` over all documents, each inside `asyncio.Semaphore(MAX_CONCURRENT_DOCUMENTS)`. `gather` keeps results in input order
  - **Decision: one semaphore shared by all requests**, created once in the processor at startup. Two simultaneous API calls still never put more than N documents in flight (a separate semaphore per request would double the load on Ollama)
  - **Decision: the semaphore covers the whole document** (download → pages → classify → extract), not only the Ollama calls. That also limits temporary files and memory; downloads take about 1 s compared with about 20 s of inference
  - `_process_limited` never raises (any escaping exception → `internal error`). Otherwise `gather` would return early and the workspace would be deleted while other documents were still using it
- [x] **Tested with `python -m scripts.test_concurrency`: 17/17 pass** (fakes with random delays, no Ollama)
  - Limits 1, 2, 3 and 5: at most N in flight, and N is reached (limit 1: 1.50 s, 2: 0.86 s, 3: 0.57 s, 5: 0.41 s)
  - Two simultaneous requests on one processor with limit 2 → still at most 2 in flight (20 documents)
  - Same result at limit 1 and limit 3, even though documents finish out of order; groups in first-seen order; documents in input order
  - 2 download errors + 1 crash among 10 → exactly those 3 have errors, 7 are fine; slots are freed after failures
  - An exception escaping `_process_one` → `internal error`, and the other 9 complete
  - Cancelled request (client disconnect): 2 of 10 had started, none started after, and the workspace was deleted
  - Waiting-bound work: limit 3 took 0.97 s vs 2.48 s at limit 1
  - `MAX_CONCURRENT_DOCUMENTS` = 3 → 3; 0 → 1; -4 → 1
- [x] `scripts/benchmark_concurrency.py`: `caffeinate -i python -u -m scripts.benchmark_concurrency 1 2 3`. **Each run uses 10 new random fake documents** (5 passports, 5 Aadhaar), because Ollama caches repeats. It warms up the model first, checks accuracy (type, owner, passport/Aadhaar number) and reports `ollama ps` memory
- [x] **Benchmarked on the MacBook Air M4** (10 documents, 2 model calls each):

  | Ollama `NUM_PARALLEL` | Run | limit 1 | limit 2 | limit 3 |
  |---|---|---|---|---|
  | 1 | 1st, order 1→2→3 | **221 s** (22.1 s/doc) | 266 s | 275 s |
  | 1 | 2nd, order 3→1 | 278 s | | 266 s |
  | 2 (temporary, 3-min cool-down) | 3rd | | **216 s** (21.6 s/doc) | |

  - Every run: **10/10 correct**, 7.4 GB, 100% GPU
  - **Ollama 0.14.1 can't run qwen3-vl in parallel.** Its log shows `WARN "model architecture does not currently support parallel requests" architecture=qwen3vl` and loads with `Parallel:1` even when `OLLAMA_NUM_PARALLEL=2`. Memory stayed at 7.4 GB (real parallel slots would add KV cache)
  - The differences between limits are **heat, not concurrency**. The fanless Air slows from about 22 s to about 27 s per document under sustained load; in the reverse-order run, limit 1 was the slow one
  - `OLLAMA_NUM_PARALLEL` was set temporarily with `launchctl setenv` + `brew services restart ollama`, then **restored** (`launchctl unsetenv`, restart; the log shows `OLLAMA_NUM_PARALLEL:1` again)
- [x] **Decision: keep `MAX_CONCURRENT_DOCUMENTS=2` on the M4.** It costs nothing measurable, and it lets the next document download and render while the model works on the current one (real network downloads take longer than the local copies in the benchmark). At most one request waits in Ollama's queue, so `OLLAMA_TIMEOUT_SECONDS=180` is safe. Going higher only lengthens Ollama's queue
- [x] Regression at limit 2: `test_document_check` 25/25 (13 URLs in 191 s, down from 180–222 s one at a time, which is within the heat noise), `test_pipelines` 20/20, `test_grouping` 13/13

#### How to benchmark and tune on another machine
1. Check the Ollama log for `model architecture does not currently support parallel requests`. If it's there, Ollama runs one request at a time and `MAX_CONCURRENT_DOCUMENTS` 1–2 is enough.
2. Otherwise set `OLLAMA_NUM_PARALLEL` (for brew: `launchctl setenv OLLAMA_NUM_PARALLEL 2 && brew services restart ollama`; on Linux systemd: `Environment=` in the service), and check `ollama ps`: memory must stay 100% GPU.
3. Run `caffeinate -i python -u -m scripts.benchmark_concurrency 1 2 3`, **with a cool-down between runs** on laptops, and repeat in reverse order.
4. Set `MODEL_PARALLEL_REQUESTS` to what Ollama really runs in parallel, and `MAX_CONCURRENT_DOCUMENTS` to that or one more, at the fastest setting that keeps 10/10 correct.

#### Speed-up: shared system prompt + model lock (after Stage 11)
- [x] **Experiment** (`scratchpad` script, direct `/api/chat` calls, fresh random passports): the same image classified then extracted
  - A, current (different system prompts): extract **9.0–9.6 s**, total 18.2–19.9 s per document
  - B, same system prompt for both calls: extract **3.1–3.2 s**, total 12.7–13.5 s
  - C, B + image in its own user message: 3.2–3.3 s (no better than B)
  - Why: Ollama puts system prompt + image before the question text, so an identical start lets it **reuse the cached image work**. `prompt_eval_count` does **not** drop (Ollama reports the full prompt size); only the timing shows the reuse. Every passport number was read correctly in every variant
- [x] `app/services/prompts.py`: **one `SYSTEM_PROMPT` for the classifier and every pipeline**, with a docstring warning that changing it for one call type silently loses the speed-up
- [x] **The cache is lost if calls interleave.** Ollama has one slot for qwen3-vl, so with 2 documents in flight the order doc A classify → doc B classify → doc A extract evicts A's image. New setting `MODEL_PARALLEL_REQUESTS` (default 1): an inner `asyncio.Semaphore` around each document's classify **and** extract, so the two calls always reach Ollama back to back. Downloads and PDF rendering stay outside it and still overlap
- [x] Tests (`test_concurrency`, now 25/25): with model limit 1, never 2 model calls at once, and **every classify is immediately followed by its own extract**; downloads still overlap (peak ≥ 2); model limit 2 → peak 2; the slot is released after a classify crash; `MODEL_PARALLEL_REQUESTS` 0 or -4 → 1
- [x] Accuracy re-checked with the new prompt: `test_classifier` **22/22**, `test_extraction` **47/47**, `test_document_check` **25/25**
  - The model now prints owner names as printed (`"JOHN DOE"` instead of `"John Doe"`). Grouping ignores case, so nothing broke; the end-to-end test was fixed to compare names case-insensitively too
- [x] **Benchmark** (limit 2, after a 10-minute rest): **145.0 s for 10 documents (14.5 s/doc), 10/10 correct**, compared with 216–221 s before. **About 34% faster**
  - A run straight after about an hour of continuous inference (3-minute cool-down only) gave 226 s. The per-call log confirmed the reuse still worked (extract 5.7–7.2 s vs classify 15.5–17.5 s, ratio about 0.4 vs about 1.0 before); heat had simply slowed everything down

### Stage 12: Hardening ✅
- [x] **Consistent error responses**, always JSON with `detail`: 422 (validation), 503 (model unavailable), 500 (`internal error`). Per-document problems stay in the 200 response (Stage 10)
- [x] `app/main.py` **`RequestValidationError` handler**: keeps only `type`, `loc` and `msg`; drops `input` and `ctx`, so submitted URLs and tokens are never echoed (the Stage 3 finding)
- [x] **Decision: 503 when the model is unavailable**, checked up front with `DocumentClassifier.is_ready()` → `OllamaClient.is_model_available()` **before anything is downloaded**. No more 200 with every document failed. If Ollama fails **mid-request**, the affected documents still get per-document errors
  - `is_model_available()` now uses a **5 s timeout** (it used the 180 s model timeout), returns `False` on non-JSON responses, and matches `name` against `name:latest`
- [x] **Safe 500s**: an `http` middleware catches any unexpected exception and returns `{"detail": "internal error"}`, logging only the exception **type** and the path. A middleware rather than an exception handler, because Starlette re-raises after a 500 handler and uvicorn would log the full traceback, which could hold document data
- [x] **Temporary files**: already deleted on every path (tested in Stages 4, 10 and 11: success, failures, cancelled request). Rechecked by the end-to-end test
- [x] **Logging decision:** keep plain `key=value`-style lines (host, kind, bytes, model, schema, duration, document index, error type). **No JSON logging**: it would need another package or custom formatter code for little gain. No personal data is logged anywhere; httpx/httpcore are at WARNING (Stage 10)
- [x] **Decision: no whole-request time limit.** Each download (30 s) and each model call (180 s) is already bounded, and cancelling a slow batch halfway would lose finished work. The README says clients need a long timeout (10 documents ≈ 2.5–4 min)
- [x] **README rewritten** (for people reading the GitHub repo): API, error table, response rules, formats, how it works, **all constraints** (stack, security, download/PDF limits, logging, performance, known limitations), setup, every `.env` key, tests, and how to tune another machine
- [x] **Tested with `python -m scripts.test_hardening`: 27/27 pass** (no Ollama)
  - 422 for 9 URLs, 51 URLs, a bad URL, `ftp://`, a missing field, an extra field, a wrong type, and invalid JSON: each has the right `type`, **only** `type`/`loc`/`msg`, and `SECRET123` from the URLs is never echoed. Nothing is downloaded for invalid requests
  - A valid request → 200, and no URL or token in the response
  - Model unavailable → **503** `{"detail": "document model is not available, try again later"}` and **0 downloads**
  - `RuntimeError` containing `SECRET123` → 500 `{"detail": "internal error"}`; the secret is in neither the response nor the logs, and the log line is `Unhandled RuntimeError on POST /document-check`
  - `GET /` still 200; OpenAPI documents the 503; tokens never reach the logs
  - `is_model_available`: pulled → True; not pulled → False; `mistral` matches `mistral:latest`; non-JSON, HTTP 500, timeout and unreachable → False; the readiness call uses a 5 s read timeout
- [x] **Real server** (uvicorn + curl, `OLLAMA_HOST=http://localhost:1`): 10 URLs → **503**; 9 URLs → 422 `too_short` with no input; broken JSON → 422 `json_invalid`; `SECRET123` appears 0 times in the log
- [x] `test_document_check` updated: Ollama down → `ModelUnavailableError` with **0 downloads**. **25/25**
- [x] Full regression: `test_downloader` 24/24, `test_pdf` 11/11, `test_grouping` 13/13, `test_pipelines` 20/20, `test_extraction --offline` 39/39, `test_concurrency` 25/25, `test_hardening` 27/27, `test_classifier` 22/22, `test_extraction` 47/47, `test_document_check` 25/25
- [x] **Security check before pushing:** `git log --all --name-only` shows no `.env`, `documents/`, PDF or image files ever committed; only `.env.example` is tracked

### Stage 13: Realistic documents, multi-page extraction, DPI re-check ✅
- [x] `scripts/make_realistic_documents.py` writes 6 harder FAKE documents (`realistic_*`, all marked SPECIMEN) to `documents/`:
  - `realistic_passport.png`: dense bilingual (Hindi/English) data page, 15 px labels, photo box, MRZ with real check digits, and decoys: file number, date of issue, place of issue (PRIYA ANJALI SHARMA, K4821937)
  - `realistic_passport_photo.jpg`: another passport as a phone photo: 75% size, tilted 4°, on a desk, blurred, noisy, JPEG quality 55 (RAHUL VERMA, Z9053318)
  - `realistic_passport_sideways.pdf`: the first passport scanned sideways (rotated 90°) into an A4 PDF
  - `realistic_e_aadhaar.pdf`: digital e-Aadhaar letter in 6.5–8 pt print, with decoy enrolment number, 16-digit VID and masked mobile, plus the cut-out card front/back (Neha Kapoor)
  - `realistic_aadhaar_card_scan.pdf`: 2 pages, a card scanned on A4 at 200 dpi, slightly tilted: **front on page 1, back (address) on page 2**. At 100 DPI the card is only about 330 px wide (Vikram Singh)
  - `realistic_itr_full.pdf`: 5-page ITR-1 style form in 8 pt, with decoys: masked Aadhaar, acknowledgement no., Gross Total Income, "Tax payable on total income", "Total Tax, Fee and Interest", refund. **Page 1 has no amounts**: total income is on page 2, tax paid and amount payable on page 3 (ARJUN MEHTA, AY 2024-25)
- [x] `scripts/test_realistic.py [--dpi N] [--pages type=N ...]`: classify + extract each document, report type, owner (name words in any order) and every field, with timings
- [x] **Baseline (DPI 100, 1 page per pipeline): 4/6 documents, 28/32 fields.** Every value returned was right; the 4 misses were all `null` (no guessing): the card's address (page 2) and the ITR's 3 amounts (pages 2–3)
- [x] **With `idCard=2 taxReturn=3`: 5/6, 31/32.** The last miss: `taxDue` was D9 "Total Tax, Fee and Interest" (1,25,572) instead of D11 "Amount payable" (15,570)
- [x] **Fixes:**
  - `taxDue` prompt and schema description now say: the balance still payable after taxes paid ("Amount payable", "Tax Payable / Due"), not the total tax liability and not the refund
  - `AadhaarPipeline.max_pages = 2`, `TaxReturnPipeline.max_pages = 3`
  - **Decision: page 1 first, more pages only if needed** (`BaseDocumentPipeline._generate`). Extract from page 1; if any field is `null` and the document has more pages, extract again with up to `max_pages` pages and fill in **only the missing fields** (page-1 values are never replaced). Extra pages cost about 15 s each, so one-page documents and ITR-V acknowledgements (everything on page 1) still take one call
  - **Context-window guard in `app/services/ollama.py`.** Probe on the full ITR at 150 DPI: 3 pages → 6,083 prompt tokens, correct; **5 pages → Ollama silently cut the prompt to 8,093 tokens (num_ctx 8192), still HTTP 200, answer `'15.'`**; 5 pages with num_ctx 16384 → 10,119 tokens, correct. Now any response whose `prompt_eval_count` is within 256 tokens of `num_ctx` raises `OllamaError("input filled the model's context window ...")`
- [x] **Result at DPI 100 with the fixes: 6/6 documents, 32/32 fields.** Single-page documents: extract about 3.5 s (unchanged); card scan 33 s and full ITR 55 s (second call with more pages)
- [x] **DPI re-check at 150: also 6/6, 32/32, but PDFs about 2× slower** (classify 32–38 s vs 15–18 s; card scan extract 74 s vs 33 s; full ITR extract 123 s vs 55 s). Images (PNG/JPEG) are unaffected. **Decision: keep `PDF_RENDER_DPI=100`**. Even the card scanned on A4 (about 330 px wide at 100 DPI) and the 6.5–8 pt e-Aadhaar/ITR print were read correctly. Only raise DPI if real documents show misreads
- [x] Offline tests: `test_pipelines` **27/27** (7 new: 2nd call only when a field is null and more pages exist; pages 1–3 sent; missing field filled, page-1 value kept; null everywhere stays null; 2 pages → 2 sent; one-page document or `max_pages=1` → no 2nd call; 2nd call failing → `ExtractionError`). `test_hardening` **32/32** (5 new context-guard checks: half of num_ctx and num_ctx − 257 → answer; num_ctx − 99 and num_ctx → `OllamaError`; no count reported → answer). `test_extraction --offline` 39/39
- [x] Regression with the model: `test_extraction` **47/47** (the 3-page ITR-V sample still takes one call: everything is on page 1; the Aadhaar front with no address is a single image, so no 2nd call), `test_classifier` **22/22**, `test_document_check` **25/25**

### Stage 14: PAN card type through the registry ✅
- [x] **Files changed** (and nothing in `app/api/`, `app/main.py` or `app/services/document_processor.py`: `git diff` on them is 0 lines):
  - `app/schemas/classification.py`: `DocumentType.PAN_CARD = "panCard"`
  - `app/services/classifier.py`: prompt option `panCard` (PAN is an ID card, NOT a tax return), and PAN removed from the `unknown` examples. `check_type_against_name` now: named PAN ("permanent account number", "pan card", "e-pan") but typed `idCard`/`taxReturn` → `panCard`; `idCard` without an Aadhaar name → `unknown`; `panCard` without a PAN name → `unknown`
  - `app/utils/normalize.py`: `to_pan` (uppercase, no spaces, must be 5 letters + 4 digits + 1 letter, otherwise kept as printed)
  - `app/schemas/extraction.py`: `PanCardData {panNumber, dateOfBirth, fatherName}`
  - `app/pipelines/pan_card.py`: `PanCardPipeline` (`max_pages` 1), added to `PIPELINE_CLASSES`
  - **Decision:** `fatherName` is extracted, because it is the one other field every PAN card prints; the holder's name is already `ownerName`
- [x] New FAKE sample `realistic_pan_card.png` (bilingual, KAVITA NAIR, BQTPK7302M, father MOHAN NAIR, DOB 19/04/1993, signature decoy)
- [x] **Tests:**
  - `test_extraction --offline` **46/46** (6 `to_pan` cases incl. 9 characters kept as printed; `PanCardData` normalises; registry has 4 pipelines)
  - `test_classifier` **28/28**: 18 cross-checks (PAN named as `idCard`/`taxReturn` → `panCard`; "e-PAN" → `panCard`; `panCard` named "Driving Licence" or `null` → `unknown`), and 9 model cases: `sample_pan_card` → panCard / SARA LEE, `realistic_pan_card` → panCard / KAVITA NAIR; driving licence still `unknown`
  - `test_extraction` **56/56**: both PAN cards exact (`FGHIJ5678K`, `1988-08-05`, `PETER LEE`; `BQTPK7302M`, `1993-04-19`, `MOHAN NAIR`, so the father's name was not confused with the holder's)
  - `test_realistic` **7/7 documents, 37/37 fields**
  - `test_document_check` **25/25**: the PAN card in the 13-URL request is now `panCard` with data, in the "Sara Lee" group; everything else unchanged
  - `test_pipelines` 27/27

### Stage 15: Optional API-key authentication and rate limiting ✅
- [x] Settings (config, `.env.example`, `.env`): `API_KEYS` (comma-separated, default empty = auth off), `RATE_LIMIT_REQUESTS=10`, `RATE_LIMIT_WINDOW_SECONDS=60` (`0` = no limit). `parse_api_keys` refuses keys under 16 characters **at startup**, and the error message doesn't include the key
- [x] `app/api/security.py` (no new packages):
  - `authorize` dependency on `POST /document-check` only (`dependencies=[Depends(authorize)]`); `GET /` stays open
  - Key in the `X-API-Key` header (`fastapi.security.APIKeyHeader`, so `/docs` gets an Authorize button). Compared with `hmac.compare_digest` (constant time). Missing or wrong → `401 {"detail": "missing or invalid API key"}` + `WWW-Authenticate: APIKey`. The 401 is logged with the client IP, never the key
  - `RateLimiter`: sliding window per client, in memory. The client is the API key (stored as a SHA-256 prefix, never the key itself) or, with auth off, the client IP. Over the limit → `429 {"detail": "too many requests, try again later"}` + `Retry-After` (seconds until the oldest request leaves the window). Idle clients are dropped once there are more than 10,000, so memory can't grow without limit
  - `app/main.py` puts `api_keys` and `rate_limiter` on `app.state` at import time (not in lifespan), so they apply to tests that call the app directly too
- **Decisions:**
  - **Auth is off by default** (empty `API_KEYS`), because the service runs on localhost; the README says to set keys before exposing it
  - **Rate limiting is on by default** (10 per minute). A request of up to 50 documents takes minutes, so 10 requests a minute is already generous
  - **Auth and the rate limit run before body validation**, so an unauthenticated caller learns nothing and costs nothing. **Exception, accepted:** a body that isn't JSON at all gets `422 json_invalid` first, because FastAPI parses JSON before dependencies run. That 422 echoes nothing and costs nothing
  - `401`s don't use up anyone's budget. **`X-Forwarded-For` is ignored** (any caller can forge it): behind a proxy, use keys or limit at the proxy
  - Per-process limiter: fine for one uvicorn worker (documented)
- [x] **Tested with `python -m scripts.test_security`: 33/33 pass** (no Ollama)
  - Limiter (fake clock): 3 allowed then refused with retry-after 6 s; separate clients; allowed again after the window; true sliding window (t=0 expired at t=11, t=9 not); idle clients forgotten past 10,000
  - Config: empty / `" , ,"` → auth off; keys trimmed; a 9-character key → `ValueError` without the key in the message
  - Auth off → 200 with no key. Auth on: no key, wrong key, different case, a prefix of a valid key and an empty key → 401 with `WWW-Authenticate`; key A and key B → 200; rejected requests never reached the processor
  - No key + invalid body → **401** (not 422); no key + broken JSON → 422 `json_invalid`, nothing echoed; valid key + invalid body → 422; `GET /` needs no key; OpenAPI has the `X-API-Key` scheme and 401/429
  - Rate limit 2/min: key A 200, 200, 429; `Retry-After: 40` after 20 s; key B has its own budget; five 401s don't use up key B's budget; key A allowed again after the window
  - Auth off: per-IP limit, and `X-Forwarded-For` doesn't get around it; a different IP has its own budget
  - Keys never appear in the logs; rate-limit log lines show `key:<hash>`
- [x] **Real server** (uvicorn, random 43-character key, limit 2/60 s): no key → 401; wrong key → 401; valid → 200, 200, then **429 with `retry-after: 60`**; `GET /` → 200; **key found 0 times in the server log**. `API_KEYS=too-short` → uvicorn refuses to start with `ValueError: API_KEYS: every key must be at least 16 characters`
- [x] `test_hardening` turns the limiter off (it sends more than 10 requests). Regression: `test_hardening` 32/32, `test_grouping` 13/13, `test_pipelines` 27/27, `test_concurrency` 25/25, `test_pdf` 11/11, `test_downloader` 24/24, `test_extraction --offline` 46/46, `test_document_check` **25/25** (through the real app with the default limiter on)

### Stage 16: Ollama upgrade and re-benchmark ✅
- [x] `brew upgrade ollama`: **0.14.1 → 0.34.4**, then `brew services restart ollama`. `qwen3-vl:8b-instruct` was kept (no re-download)
- [x] Smoke test (`check_ollama`): passport / JOHN DOE. The new version loads qwen3-vl through llama.cpp (`llama_model_loader`), 37/37 layers on the GPU; **memory 5.9 GB instead of 7.4 GB** (the brew service now enables flash attention and a q8_0 KV cache)
- [x] **Parallel check:** set `OLLAMA_NUM_PARALLEL=2` (`launchctl setenv` + restart). The log still says **`WARN "model architecture does not currently support parallel requests" architecture=qwen3vl`**, and llama.cpp reports `n_seq_max = 1`. **qwen3-vl still can't run in parallel**, so the parallel benchmarks (limit 2/3 with `MODEL_PARALLEL_REQUESTS=2`) were skipped as pointless. Restored with `launchctl unsetenv` + restart; the log shows `OLLAMA_NUM_PARALLEL:1`
- [x] **The shared-prompt speed-up still works:** 3 fresh random passports classified then extracted: classify 14.3 / 15.4 / 15.9 s, extract 3.3 / 3.3 / 3.4 s (ratio about 0.22; 0.14.1 gave the same kind of numbers)
- [x] **Benchmark** (`benchmark_concurrency 2`, 10 fresh documents, default settings): **198.5 s** after a 5-minute cool-down and **205.4 s** after a 10-minute rest, both **10/10 correct**, 5.9 GB, 100% GPU
  - Compared with **145 s** on 0.14.1 (rested). **Cause not isolated:** per-call timings on the same kind of image are unchanged, the Mac was on **battery at 28%** (Low Power Mode off) after a full day of inference, and a fanless Air slows under heat (Stage 11 saw 226 s when hot). 0.14.1 is no longer installed, so a same-conditions A/B isn't possible
  - **To do on a cold machine on mains power:** `caffeinate -i python -u -m scripts.benchmark_concurrency 2`. If it's still about 200 s, the new engine is slower for this model; consider pinning an older Ollama
- **Decision: keep `MAX_CONCURRENT_DOCUMENTS=2`, `MODEL_PARALLEL_REQUESTS=1`**, unchanged: Ollama still runs qwen3-vl one request at a time

### Stage 17: Tests converted to pytest ✅
- [x] **Decision (approved by the user asking for all 5 steps):** pytest is the only new package, and it's **dev-only** in `requirements-dev.txt` (`-r requirements.txt` + `pytest>=8`). The app's runtime stack is unchanged. Async tests use **anyio's pytest plugin** (anyio is already installed with httpx/Starlette), so there's no `pytest-asyncio`
- [x] `pytest.ini`: `testpaths = tests`, `pythonpath = .`, markers `model` (needs Ollama) and `network` (needs internet), **`addopts = -m "not model and not network"`**, so plain `pytest` is the fast offline run; PyMuPDF's SWIG deprecation warnings are filtered
- [x] `tests/conftest.py`: `samples` (generates missing fake documents through the new `make_all()` in both generator scripts), `settings`, `ollama` (**skips** the test if the model isn't available), `workspaces`, and an autouse fixture that restores `app.dependency_overrides`, `api_keys` and `rate_limiter` after each test
- [x] Every old `scripts/test_*.py` check was moved to `tests/` (checks grouped into test functions with plain `assert`, cases parametrized) and the old scripts deleted:
  - `test_url_safety.py` is **new**: the 22 Stage 4 SSRF cases were only run by hand before; 17 run offline (IP literals, localhost, IPv6 tricks, decimal IP, schemes, credentials), 5 need DNS
  - `test_document_check.py`: the 13-URL request runs **once** in a module-scoped fixture, and each expectation (per document, grouping, no echoed URLs, workspace deleted) is its own test
  - `test_realistic.py` takes its cases from `scripts/evaluate_realistic.py` (was `scripts/test_realistic.py`: still the field-by-field report tool with `--dpi` / `--pages`)
  - `scripts/test_ollama.py` → `scripts/check_ollama.py` (a manual tool, not a test)
- [x] **Tested:**
  - `pytest`: **177 passed, 74 deselected in 16 s**
  - `caffeinate -i pytest -m ""`: **251 passed in 9 min 48 s** (slowest: the 13-URL request 88 s, full ITR 68 s, card scan 51 s)
  - `OLLAMA_HOST=http://localhost:1 pytest -m model`: **45 skipped**, none failed
  - **The tests catch real bugs** (each deliberate bug added then reverted with `git checkout`): context-guard margin 0 → 1 test failed; auth check disabled → 7 failed; "always make the 2nd call" → 1 failed; null words kept by `clean_text` → 6 failed

### Stage 18: File upload endpoint ✅
- [x] **Decisions (user, 2026-09-28):** frontend in **plain HTML/CSS/JS** served by FastAPI (no Node, no new framework), with **URLs and file upload**. Upload needs **`python-multipart`** (FastAPI's official form parser), now in `requirements.txt`; the user approved it by choosing upload
- [x] `POST /document-check/upload`: 1–50 files in parts named `files`
  - **The body is parsed by the endpoint, not by FastAPI**, so auth, the rate limit (the `authorize` dependency), `Content-Type` (415), `Content-Length` (411 if missing, 413 over `MAX_UPLOAD_REQUEST_BYTES`, default 100 MB) and the model check (503) all happen **before any uploaded byte is read**
  - `request.form(max_files=51, max_fields=0)`: a text field or 52+ files → 400; 0 or 51 files → 422. The form is always closed, which deletes Starlette's spooled temp files
  - **Decision:** 1–50 files. The brief's minimum of 10 applies to `documentUrls`; for uploads 1 is more useful
- [x] `app/services/uploads.py` `save_upload()`: copies in 1 MB chunks into the private workspace, at most `MAX_DOWNLOAD_BYTES` per file, rejects empty files, **type from magic bytes only** (`detect_kind`, now shared with the downloader), saved as `document.<pdf|png|jpg>`; no partial file left. The client's file name and content type are never used or logged
- [x] `DocumentProcessor` refactor: each document has a **fetch** step (`_download(url)` or `_save_upload(file)`); `process(urls)` and `process_uploads(files)` share `_run()`, so pages → classify → extract → group is the same code. New `ensure_ready()`. Upload problems → per-document `error: "upload rejected: ..."`
- [x] **Tested:** `tests/test_upload.py` **22 passed** (21 offline + 1 model):
  - `save_upload`: PDF/PNG/JPEG named by content; text, empty and oversized files rejected with no partial file
  - Endpoint: 3 valid files → 200 in order, workspace deleted; a text file among valid ones fails alone; a file over the per-file limit fails alone; file name `SECRET-...` in neither response nor logs; 0 files → 422, 50 → 200, 51 → 422, 52 → 400; text field → 400; JSON → 415; **no Content-Length → 411, 413 over the limit, 503 model down, 401 without a key: in all four the body was never read** (checked with a body that records reads); OpenAPI documents the multipart body and statuses
  - Model: passport + Aadhaar + tax return uploaded → John Doe [passport, taxReturn], Maria Doe [idCard]
  - Real server (uvicorn + curl): passport, PAN card, receipt → JOHN DOE / SARA LEE / no owner in 41 s; **120 MB upload → 413 in 2 ms, 0 bytes sent**; JSON → 415; file name 0 times in the log; no temp folders left
  - Regression: `pytest` **198 passed** (offline)

### Stage 19: Web page ✅
- [x] `app/static/index.html`, `style.css`, `app.js`, `favicon.svg`: plain HTML/CSS/JS (no framework, no build step), mounted at **`/ui/`** with `StaticFiles(html=True)` in `app/main.py` (`/ui` → 307 → `/ui/`)
  - Tabs **Upload files** (drag and drop or choose, file list with sizes and Remove, warning over 20 MB) and **Document URLs** (textarea, live count); client-side checks (1–50 files, 100 MB total; 10–50 http(s) URLs) before sending
  - API key field (collapsed): kept in memory, or `sessionStorage` if "Remember for this browser tab" is ticked. **Decision: never `localStorage`**
  - Progress line with elapsed seconds and "usually 15–20 s per document"; **Cancel** (`AbortController`)
  - Results: summary (documents, owners, problems, seconds), one card per owner (`No owner found` for null), per document: type badge, name, `#n · file name or URL host` (the file name only ever lives in the browser), field table with friendly labels (`not visible` for null), error box; **Copy JSON** / **Download JSON**
  - Plain-language errors for 401, 429 (with `Retry-After`), 503, 413, 422, other statuses and "server offline"; server status pill from `GET /`
  - Light/dark via `prefers-color-scheme`, focus outlines, arrow keys between tabs, one-column layout under 600 px
- [x] **Security decisions:**
  - Everything from the server (including model output) is rendered with `textContent` / `createElement`, **never `innerHTML`**
  - `/ui` responses get `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. So no inline scripts, styles or CDNs in the page
- [x] **Tested:**
  - `tests/test_ui.py` **11 passed**: redirect; the 4 files served with the right types and all headers; `../` and `%2e%2e` traversal and a missing file → 404; API routes don't get UI headers; `app.js` contains no `.innerHTML` / `.outerHTML` / `insertAdjacentHTML` / `document.write` / `eval(` / `new Function` (**a deliberately added `innerHTML` line made it fail**); `index.html` has no inline script, style, event handler or external file
  - **Driven in headless Chrome** (scratchpad script over the DevTools protocol, using the `websockets` package that comes with uvicorn): status pill "Server online"; URL tab with 2 URLs → "Enter 10 to 50 URLs (you have 2)"; empty upload → "Choose at least one file"; **passport + PAN card + tax return uploaded → 3 documents, owners JOHN DOE (Passport, Tax return) and SARA LEE (PAN card) in 23 s**; dark mode and 390 px phone width checked by screenshot, no horizontal scroll
  - **XSS check:** rendering a response with `<img onerror>`, `<script>`, `<svg onload>` in the owner, name, field, error and source label → 0 elements created, nothing ran, the owner shown as literal text
  - Error states against extra servers: `API_KEYS` + limit 1 → 401 message, then with the key → results, then 429 "Try again in 59 seconds"; Ollama down → 503 message; the key appeared 0 times in the server log
  - **Console: no JS errors and no CSP violations.** The only entries are the browser logging the deliberate 401/429/503 responses and Chrome's "password field is not in a form" hint (harmless: the key is never submitted as a form)
  - `docs/screenshot.png` (light mode, 4 fake documents, 3 owners) added to the README
  - Regression: `pytest` **209 passed** (offline)

### Stage 20: n8n workflow (Form → ExtractAI → Google Sheets)
- [x] **Decisions (user, 2026-09-28):** trigger = **n8n Form upload**, output = **Google Sheets**. n8n runs **locally in Docker** (free; can reach the API on this Mac; documents stay local until the rows go to Sheets)
- [x] `n8n/docker-compose.yml`: `n8n:latest` (**2.40.7**), port bound to `127.0.0.1:5678`, `host.docker.internal` → the Mac, telemetry off, binary data on disk, **executions pruned after 24 h**. Docker Hub failed once with `unexpected EOF` while fetching a token; a retry worked
- [x] Owner account created through `/rest/owner/setup` as `admin@example.com` with a random password in **`n8n/.login.txt` (gitignored, mode 600)**. Scripted REST access needs a `browser-id` header and the `n8n-auth` cookie sent explicitly (it's marked Secure)
- [x] `n8n/extractai-workflow.json` (importable; the credential is referenced by name):
  - **Upload documents** (Form Trigger 2.6, path `extractai`, multi-file field, `.pdf, .png, .jpg, .jpeg`) → **One item per file** (Code) → **ExtractAI: extract data** (HTTP Request 4.2, `POST http://host.docker.internal:8000/document-check/upload`, multipart field `files`, Header Auth credential `ExtractAI API key`, 3 tries / 5 s apart, 10 min timeout, **on error: continue**) → **Rows for Sheets** (Code) → **Summary** (Code) → **Show result** (Form 2.5, Form Ending)
  - **Decision: one request per file.** The n8n source (`HttpRequestV3`) shows each `formBinaryData` parameter maps to one binary field, so a variable number of files can't go in one request. With one document per request, the API's owner grouping is recreated in the Summary node (case-insensitive)
  - n8n splits a JSON **array** response into items, so each HTTP item is one owner group (found in testing; code adjusted)
  - Rows: Processed at, File, Owner, Type, Document name, ID number (passport / **masked Aadhaar** / PAN), Date of birth, Details, Error. HTTP errors are shortened to `HTTP 401: missing or invalid API key`
  - Summary text is HTML-escaped before it's shown on the form's result page
  - Workflow settings: successful executions not saved; failed ones saved (and pruned after 24 h)
- [x] **Tested with real runs** (form submitted with curl like the browser does; the result page read from `/form-waiting/<id>`):
  - passport + PAN card → *"2 documents processed — JOHN DOE: Passport | SARA LEE: PAN card"* (50 s)
  - Aadhaar + a text file named `.png` + tax return → *"3 documents processed — MARIA DOE: Aadhaar | JOHN DOE: Tax return | Problems: fake.png (upload rejected: ...)"*; rows checked: Aadhaar **`XXXX-XXXX-0123`**, file names matched to the right rows although n8n sent the requests in parallel, the fake file became an error row
  - **Wrong API key** in the credential → API 401 (retried 3×), error row, result page lists the problem, workflow finished; key found 0 times in the API log; key restored
  - Passport with no visible name → row with blank owner and extracted data
  - A form submitted right after re-publishing hit "webhook is not registered" once; a second later it worked (n8n registers the form asynchronously)
  - All test executions deleted afterwards; no uploaded files left in n8n's storage
- [x] **Storage without Google (user asked to finish it without them):** this session has no Google or browser tools, and connecting Google needs the user's own sign-in and consent. So:
  - **n8n Data Table `ExtractAI results`** (created through `POST /rest/projects/:id/data-tables`; text columns `processedAt, file, owner, type, documentName, idNumber, dateOfBirth, details, error`) and a **Save to n8n table** node (Data Table 1.1, insert, table referenced **by name** so the JSON imports anywhere). Data stays on this machine; CSV download from the n8n UI
  - **Google Sheets: append rows** node (4.7, OAuth2, append, auto-map by column name) added **disabled**, with a note on what to select. A disabled node passes items through, so the chain keeps working
  - Order: Rows for Sheets → Google Sheets (off) → Save to n8n table → Summary. The table node reads from `$('Rows for Sheets')`, so it works whether Sheets is on or off
  - **Tested:** passport + Aadhaar → result page *"JOHN DOE: Passport | MARIA DOE: Aadhaar"*, **2 rows in the n8n table** (Aadhaar `XXXX-XXXX-0123`), CSV download works. **Bug found and fixed:** "Processed at" was UTC (`new Date().toISOString()`); now `$now.toFormat(...)` in n8n's timezone (Asia/Kolkata), checked: 23:30 matched the clock. Test executions deleted; the 3 fake test rows were left in the table as examples
- [x] The user created a Google Sheet (2026-09-28). In the **local** n8n workflow, the *Google Sheets: append rows* node now points at it (first tab, gid 0); still disabled. **The sheet URL is deliberately not in the repo**: `n8n/extractai-workflow.json` stays generic
- [ ] **Google Sheets (user):** paste the 9 column names into row 1, create the Google Cloud OAuth client, add the *Google Sheets OAuth2 API* credential in n8n, select it in the node and enable it (steps in README "n8n workflow"); then run one test upload and check the rows appear in the sheet

---

## 6. File map (what exists now)

```
app/main.py                    FastAPI app, lifespan (shared clients), logging, 422 handler, 500 middleware, GET /; api_keys + rate_limiter on app.state
app/config.py                  Settings from .env (get_settings, parse_api_keys)
app/api/document_check.py      POST /document-check (URLs) and POST /document-check/upload (1-50 files, body parsed after all checks)
app/static/                    the web page at /ui/: index.html, style.css, app.js (textContent only), favicon.svg
docs/screenshot.png            README screenshot (fake documents)
n8n/docker-compose.yml         local n8n 2.x (127.0.0.1:5678, host.docker.internal, 24 h pruning)
n8n/extractai-workflow.json    importable workflow: Form -> ExtractAI -> rows (Aadhaar masked) -> [Google Sheets] -> summary page
n8n/.login.txt                 local n8n login (gitignored)
app/services/uploads.py        save_upload(): uploaded file -> workspace, size cap, type from magic bytes
app/api/security.py            optional X-API-Key auth + RateLimiter (sliding window per key / IP)
app/schemas/request.py         DocumentCheckRequest (10-50 http(s) URLs)
app/schemas/classification.py  DocumentType enum (+ panCard) + Classification (documentName first!)
app/schemas/extraction.py      PassportData, AadhaarData (aadharNumber), TaxReturnData (assessmentYear), PanCardData
app/schemas/response.py        DocumentResult (+ sourceIndex, error) and OwnerResult
app/services/ollama.py         OllamaClient.generate_structured -> validated Pydantic model; context-window guard
app/services/prompts.py        the ONE shared SYSTEM_PROMPT (cache reuse between classify and extract)
app/services/classifier.py     DocumentClassifier.classify(page_images) -> Classification (+ check_type_against_name)
app/services/grouping.py       group_by_owner(items, owner_of) -> [OwnerGroup(ownerName, documents)]
app/services/downloader.py     DocumentDownloader.download(url, dest_dir, name)
app/services/document_processor.py   DocumentProcessor.process(urls): readiness check, documents concurrently (outer semaphore + model lock), then group
app/pipelines/base.py          BaseDocumentPipeline(ABC): extract(page_images); _generate = page 1 first, more pages only if fields are null
app/pipelines/registry.py      PipelineRegistry (get / extract / build) + PIPELINE_CLASSES
app/pipelines/passport.py      PassportPipeline      (document_type "passport")
app/pipelines/aadhaar.py       AadhaarPipeline       (document_type "idCard", max_pages 2)
app/pipelines/tax_return.py    TaxReturnPipeline     (document_type "taxReturn", max_pages 3)
app/pipelines/pan_card.py      PanCardPipeline       (document_type "panCard")
app/utils/url_safety.py        SSRF check: resolve_public_ip(url)
app/utils/workspace.py         request_workspace(): private temp dir, always deleted
app/utils/pdf.py               to_page_images(): PDF -> PNG pages, images pass through
app/utils/normalize.py         clean_text, to_iso_date, to_aadhaar_number, to_amount, to_pan

tests/conftest.py              fixtures: samples (generated if missing), settings, ollama (skips if unavailable), app-state cleanup
tests/test_*.py                251 pytest tests: 177 offline, 45 `model`, 47 `network` (some are both) (see README "Tests")
pytest.ini                     testpaths, pythonpath, markers; plain `pytest` = offline only
requirements-dev.txt           requirements.txt + pytest (dev only)

scripts/make_sample_documents.py     make_all(): fake passport (png, scan pdf, no-name), tax return pdf, aadhaar (+ front only), driving licence, PAN card, receipt
scripts/make_realistic_documents.py  make_all(): realistic_* (dense passport, phone photo, sideways scan, e-Aadhaar, card scan front/back, 5-page ITR, PAN card)
scripts/check_ollama.py              manual check that the model answers (was test_ollama.py)
scripts/evaluate_realistic.py        field-by-field report on realistic_*; --dpi / --pages to compare settings (was test_realistic.py); its CASES feed tests/test_realistic.py
scripts/benchmark_concurrency.py     real-model benchmark: 10 fresh random documents per run, accuracy + ollama ps
README.md                      public project README
CLAUDE.md                      tells the AI assistant to start from this file
PROGRESS.md                    this file
```

---

## 7. Current state and next action

**Status: Stages 1–20 are done and pushed.** The n8n workflow saves results to n8n's own table; the Google Sheets node is ready but switched off until the user connects their Google account. The brief (Stages 1–12), the 5 follow-ups (13–17), and the frontend (18: upload endpoint, 19: web page at `/ui/`).

**To use it:** `source .venv/bin/activate && uvicorn app.main:app`, then open http://127.0.0.1:8000/ui/

**Possible next steps (ask the user):**
1. Re-run `caffeinate -i python -u -m scripts.benchmark_concurrency 2` on a **cold Mac on mains power**, to settle whether Ollama 0.34.4 is slower than 0.14.1 (Stage 16).
2. Live progress on the page (per-document status as each finishes) would need a streaming endpoint (e.g. Server-Sent Events); today the page waits for the whole batch.
3. Test with real-world scans (only documents the user has the right to process), and adjust DPI / `max_pages` if needed.
4. Add a driving licence type the same way as the PAN card (Stage 14).
