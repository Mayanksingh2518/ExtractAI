from fastapi import FastAPI

app = FastAPI(
    title="Document Intelligence API",
    description="Classifies documents and extracts structured data using a local Ollama vision model.",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "document-intelligence-api"}
