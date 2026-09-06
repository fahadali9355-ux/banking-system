# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Response, HTTPException
from app.models.transactions import (
    ExecuteTransferRequest, ExecuteTransferResponse,
    ReverseTransactionRequest, ReverseTransactionResponse,
    CreateApprovalRequest, CreateApprovalResponse,
    ResolveApprovalRequest, ResolveApprovalResponse
)
from app.services.transactions import (
    execute_transfer,
    reverse_transaction,
    create_approval_request,
    resolve_approval
)

router = APIRouter()

@router.post("/execute", response_model=ExecuteTransferResponse)
async def execute_transfer_endpoint(req: ExecuteTransferRequest, response: Response):
    res, status_code = await execute_transfer(req)
    response.status_code = status_code
    return res

@router.post("/reverse", response_model=ReverseTransactionResponse)
async def reverse_transaction_endpoint(req: ReverseTransactionRequest, response: Response):
    res, status_code = await reverse_transaction(req)
    response.status_code = status_code
    return res

@router.post("/approval-requests", response_model=CreateApprovalResponse)
async def create_approval_request_endpoint(req: CreateApprovalRequest):
    return await create_approval_request(req)

@router.post("/approval-requests/resolve", response_model=ResolveApprovalResponse)
async def resolve_approval_endpoint(req: ResolveApprovalRequest, response: Response):
    res, status_code = await resolve_approval(req)
    response.status_code = status_code
    return res
