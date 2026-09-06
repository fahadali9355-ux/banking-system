from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class VerifyPasswordRequest(BaseModel):
    account_holder_id: str
    account_id: str
    action_type: str  # "TRANSACTION" or "STATEMENT"
    password: str
    challenge_code: Optional[str] = None

class VerifyPasswordResponse(BaseModel):
    request_id: str
    match: bool
    challenge_code_valid: Optional[bool] = None
    failed_attempts: int
    account_status: str

class VerifyOtpRequest(BaseModel):
    context: str
    reference_id: str
    otp: str

class VerifyOtpResponse(BaseModel):
    request_id: str
    verified: bool

class IssueChallengeCodeRequest(BaseModel):
    account_id: str
    thread_id: str

class IssueChallengeCodeResponse(BaseModel):
    request_id: str
    code: str
    expires_at: datetime
