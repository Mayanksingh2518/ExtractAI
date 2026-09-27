from fastapi import FastAPI

from app.api.document_check import router as document_check_router

app = FastAPI(
    title="Document Intelligence API",
    description="Classifies documents and extracts structured data using a local Ollama vision model.",
    version="0.1.0",
)

app.include_router(document_check_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "document-intelligence-api"}
