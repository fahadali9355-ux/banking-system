from pydantic import BaseModel

class PiiRedactRequest(BaseModel):
    text: str

class PiiRedactResponse(BaseModel):
    request_id: str
    redacted_text: str
    token_map_id: str

class PiiRestoreRequest(BaseModel):
    token_map_id: str
    text: str

class PiiRestoreResponse(BaseModel):
    request_id: str
    restored_text: str
