# ExtractAI: Document Intelligence API

A FastAPI service that downloads identity and tax documents, classifies them with a **local** vision LLM (Ollama + Qwen3-VL), groups them by owner, and extracts structured data using a document-type-specific pipeline.

All inference runs on your own machine. Documents are never sent to a third-party AI service.

> **Status:** work in progress, built step by step as a learning project.
> Stages 1–2 are done (project skeleton + Ollama service). The `POST /document-check` endpoint is not built yet.

## Planned API

`POST /document-check` accepts at least 10 document URLs (PDF, PNG, JPG/JPEG):

```json
{ "documentUrls": ["https://example.com/doc1.pdf", "..."] }
```

and returns documents grouped by owner, with type-specific extracted data:

```json
[
  {
    "ownerName": "John Doe",
    "documents": [
      {
        "documentType": "passport",
        "documentName": "Indian Passport",
        "data": { "passportNumber": "AB123456", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31" }
      }
    ]
  }
]
```

Supported document types: `passport`, `idCard` (Aadhaar), `taxReturn`, and `unknown`. Any field that isn't visible on the document is returned as `null`. The model is instructed never to guess.

### Processing flow

1. Validate the request (at least 10 URLs).
2. Download each document safely (SSRF protection, size and time limits, file-type allowlist).
3. Convert PDFs to page images with PyMuPDF. Images are used as they are.
4. Classify each document with the vision model to get `documentType`, `documentName` and `ownerName`, then validate the result with Pydantic.
5. Group the documents by owner.
6. Run the extraction pipeline for each document type, chosen from a registry. Adding a new type doesn't require changing the API code.
7. Return the combined JSON.

## Tech stack

Python 3.11+, FastAPI, Uvicorn, Pydantic v2, httpx, PyMuPDF, Pillow, python-dotenv, [Ollama](https://ollama.com) with `qwen3-vl`.

Ollama is called directly through its REST API (`/api/chat`) with httpx. Only `app/services/ollama.py` knows about Ollama.

## Project structure

```
app/
├── main.py            # FastAPI app
├── config.py          # Settings loaded from .env
├── api/               # Route handlers (planned)
├── schemas/           # Request/response models (planned)
├── services/
│   └── ollama.py      # Ollama client: images + prompt -> validated Pydantic model
├── pipelines/         # Per-document-type extraction + registry (planned)
└── utils/             # PDF -> image conversion (planned)
scripts/
└── test_ollama.py     # Manual check for the Ollama service
```

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
brew services start ollama        # or install the Ollama macOS app
ollama pull qwen3-vl:8b-instruct  # ~6 GB
```

Choose the model size to fit your machine's memory:

| RAM / VRAM | Model |
|---|---|
| ≤ 8 GB | `qwen3-vl:4b-instruct` |
| 16 GB (e.g. M-series Mac) | `qwen3-vl:8b-instruct` |

The `-instruct` versions don't produce "thinking" text, which makes them faster for extraction work.

### 3. Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Document Intelligence API` | App title |
| `LOG_LEVEL` | `INFO` | Logging level |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server. Keep this local |
| `OLLAMA_MODEL` | `qwen3-vl:8b-instruct` | Vision model to use |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Timeout for each model call |
| `OLLAMA_NUM_CTX` | `8192` | Context window. Ollama's default of 4096 can cut off document images without warning |

## Running

```zsh
source .venv/bin/activate
uvicorn app.main:app --reload
```

- Health check: `curl http://127.0.0.1:8000/` returns `{"status":"ok","service":"document-intelligence-api"}`
- Interactive docs: http://127.0.0.1:8000/docs

### Test the Ollama service on its own

Put a test image in `documents/` (the folder is gitignored), then run:

```zsh
python -m scripts.test_ollama documents/sample_passport.png
```

Expected output:

```
model: qwen3-vl:8b-instruct
model available: True
result: {'documentType': 'passport', 'documentName': '...', 'ownerName': '...'}
```

## Security and privacy

These documents contain sensitive personal data. The project is designed so that:

- The LLM runs locally and nothing is sent to external AI services.
- Raw document contents and full LLM responses are never logged.
- Downloads will be protected against SSRF, including private, loopback and link-local IPs, checked again after DNS resolution and on redirects. Downloads will also have size limits, timeouts and a file-type allowlist.
- Each request will get a private temporary folder that is always deleted afterwards. Downloaded files are never served.

Only use documents you have the right to process. Use made-up sample documents for testing.

## Roadmap

- [x] 1. Project skeleton, venv, FastAPI `/` endpoint
- [x] 2. Ollama setup and `app/services/ollama.py`
- [ ] 3. `POST /document-check` with minimum-10-URL validation
- [ ] 4. Safe document downloading
- [ ] 5. PDF to image conversion
- [ ] 6. Classification with the vision model
- [ ] 7. Group by owner
- [ ] 8. Pipeline architecture (base class + registry)
- [ ] 9. Passport, Aadhaar and tax return pipelines
- [ ] 10. Connect everything and return the final JSON
- [ ] 11. Controlled concurrency (`asyncio.Semaphore`, `MAX_CONCURRENT_DOCUMENTS`)
- [ ] 12. Hardening: error handling, cleanup, logging
