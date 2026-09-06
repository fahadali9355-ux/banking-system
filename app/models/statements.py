from pydantic import BaseModel

class StatementRequest(BaseModel):
    account_id: str
    period_start: str
    period_end: str

class StatementResponse(BaseModel):
    request_id: str
    pdf_base64: str
    filename: str
