# ExtractAI: Project Brief and Progress

**This file is the single source of truth for the project.** It records the task, the rules, what has been built and tested, and the exact next step.
On any machine or in any new session, reading this file should be enough to carry on without anyone explaining the context again.

_Last updated: 2026-09-24_

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
| MacBook Air M4 | 16 GB unified, Ollama 0.14.1, Python 3.11.14 | `qwen3-vl:8b-instruct` (download in progress; `qwen3-vl:8b` already installed) | 2 (to be benchmarked) | Stage 2 was done here. 8b runs 100% on the GPU, about 7 GB |

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

### Stage 2: Ollama service ✅ (one follow-up left, see section 7)
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
- [ ] Switch to `qwen3-vl:8b-instruct` and compare its speed. **Next action, see section 7**

#### What the Stage 2 tests showed

| Finding | What we did |
|---|---|
| The first prompt put extra fields into `ownerName` (`"JOHN DOE (Surname: DOE, Passport No.: ...)"`) | Added a system prompt, a `description` on each schema field, and clearer instructions. The result is now `"JOHN DOE"`. Use the same approach for every prompt |
| Ollama's default context window is 4096 tokens, and one small image already used about 1,400 | Set `num_ctx: 8192` (`OLLAMA_NUM_CTX`). Otherwise large PDF pages are cut off **without any error**. Keep this in mind when choosing the PDF render DPI in Stage 5 |
| `qwen3-vl:8b` ignores `think: false` and still writes about 630 characters of reasoning | Still usable, because the reasoning comes back in a separate field. Switching to `qwen3-vl:8b-instruct` for speed |
| Pydantic's enum and `str \| None` schemas (`$defs`, `anyOf`) | Ollama accepts them, so the schemas can be passed in directly |
| Timing on the M4 with `8b`: about 6 s to load the first time, then about 13–20 s per document (image processing about 7 s, generation about 4 s) | Starting point for tuning in Stage 11 |

### Stage 3: `POST /document-check` with validation of at least 10 URLs ⬜
- [ ] `app/schemas/request.py`: `DocumentCheckRequest` with `documentUrls: list[HttpUrl]` and `min_length=10`
- [ ] `app/api/document_check.py`: an `APIRouter` with `POST /document-check`, included in `app/main.py`. For now it just echoes the number of URLs back
- [ ] Tests (curl or `/docs`): 10 URLs → 200; 9 URLs → 422; a URL that isn't valid → 422; `documentUrls` missing → 422

### Stage 4: Downloading documents ⬜
- [ ] `app/services/downloader.py` using httpx streaming, with settings in `.env` (max size, timeout)
- [ ] SSRF protection: only `http`/`https`; resolve DNS and reject private, loopback, link-local, reserved and multicast IPs; follow redirects manually and check each one again
- [ ] Check the status, the maximum file size (stop the stream early), and the allowlist (content-type **and** the file's first bytes: `%PDF`, the PNG header, the JPEG `FFD8FF`)
- [ ] A private temporary folder per request (`tempfile.mkdtemp`, mode 0700), always deleted in a `finally` block
- [ ] Tests: a good URL; 404; file too large; wrong type; `http://127.0.0.1/`; `http://169.254.169.254/`; `http://localhost/`; a redirect to a private IP; a timeout

### Stage 5: PDF to image conversion ⬜
- [ ] `app/utils/pdf.py` using `import pymupdf`. Render pages to PNG at a sensible DPI and keep the original. Images are used as they are
- [ ] Test: a multi-page PDF produces one PNG per page, and an image input isn't converted again

### Stage 6: Classification ⬜
- [ ] `app/schemas/`: the `DocumentType` enum and a `Classification` model (move them out of `scripts/test_ollama.py`)
- [ ] `app/services/classifier.py`, built on `OllamaClient.generate_structured`
- [ ] Tests (fake samples): passport, Aadhaar, tax return; an unrelated image → `unknown`; a document with no visible name → `ownerName: null`

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
- [ ] Temporary files cleaned up on every path
- [ ] Structured logging with no personal data
- [ ] Final README pass

---

## 6. File map (what exists now)

```
app/main.py                    FastAPI app + GET /
app/config.py                  Settings from .env (get_settings)
app/services/ollama.py         OllamaClient.generate_structured -> validated Pydantic model
app/{api,schemas,pipelines,utils}/__init__.py   empty, filled in by later stages
scripts/make_sample_documents.py   writes fake documents/sample_passport.png
scripts/test_ollama.py         manual check of the Ollama service
README.md                      public project README
CLAUDE.md                      tells the AI assistant to start from this file
PROGRESS.md                    this file
```

---

## 7. Current state and next action

**Status:** Stage 2 is done and pushed. On the M4 Mac, `qwen3-vl:8b-instruct` was still downloading when this was last updated.

**Next action:**
1. Make sure `qwen3-vl:8b-instruct` is pulled (`ollama list`), and set `OLLAMA_MODEL=qwen3-vl:8b-instruct` in `.env`.
2. Run `python -m scripts.test_ollama documents/sample_passport.png`. Confirm the result is correct and compare the time with `8b` (about 13 s). Record the result in section 5 and tick the last item in Stage 2.
3. If `8b-instruct` works well, you can remove `qwen3-vl:8b` to free 6 GB (`ollama rm qwen3-vl:8b`). **Ask the user first.**
4. Start **Stage 3, step 1**: create `app/schemas/request.py`.
