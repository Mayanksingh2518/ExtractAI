from pydantic import BaseModel, ConfigDict, Field, HttpUrl

MIN_DOCUMENTS = 10
MAX_DOCUMENTS = 50  # upper bound so a single request can't queue unbounded work


class DocumentCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documentUrls: list[HttpUrl] = Field(
        min_length=MIN_DOCUMENTS,
        max_length=MAX_DOCUMENTS,
        description=f"Between {MIN_DOCUMENTS} and {MAX_DOCUMENTS} http(s) URLs of PDF, PNG or JPG documents.",
    )
