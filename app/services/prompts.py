"""The one system prompt shared by every model call.

Classification and extraction MUST use the same system prompt: the model sees
system prompt + image first, so an identical start lets Ollama reuse the work it
did on the image in the classify call for the extract call (Stage 11: extract
9 s -> 3 s). Changing it for one call type silently loses that speed-up.
"""

SYSTEM_PROMPT = (
    "You read identity and tax documents: you classify them and extract their data. "
    "Report only what is clearly visible in the image, and copy values exactly as printed. "
    "Never guess, calculate or invent values. If a field is not visible or not readable, use null."
)
