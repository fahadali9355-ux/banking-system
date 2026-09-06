from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ExecuteTransferRequest(BaseModel):
    idempotency_key: str
    from_account_id: str
    to_account_id: str
    amount: str
    type: str
    initiated_by_holder_id: str
    description: Optional[str] = None

class ExecuteTransferResponse(BaseModel):
    request_id: str
    status: str
    transaction_id: Optional[str] = None
    new_balance: Optional[str] = None
    reason: Optional[str] = None

class ReverseTransactionRequest(BaseModel):
    original_transaction_id: str
    reason: str
    approved_by: str

class ReverseTransactionResponse(BaseModel):
    request_id: str
    reversal_transaction_id: str
    new_balance: str

class CreateApprovalRequest(BaseModel):
    account_id: str
    idempotency_key: str
    initiated_by: str

class CreateApprovalResponse(BaseModel):
    request_id: str
    approval_request_id: str
    expires_at: datetime

class ResolveApprovalRequest(BaseModel):
    approval_request_id: str
    holder_id: str
    decision: str

class ResolveApprovalResponse(BaseModel):
    request_id: str
    status: str
    ready_to_execute: Optional[bool] = None
