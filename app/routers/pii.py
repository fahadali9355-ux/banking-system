from fastapi import APIRouter
from app.models.pii import (
    PiiRedactRequest, PiiRedactResponse,
    PiiRestoreRequest, PiiRestoreResponse
)
from app.services.pii import redact_text, restore_text

router = APIRouter()

@router.post("/redact", response_model=PiiRedactResponse)
async def redact_text_endpoint(req: PiiRedactRequest):
    res = await redact_text(req)
    return res

@router.post("/restore", response_model=PiiRestoreResponse)
async def restore_text_endpoint(req: PiiRestoreRequest):
    res = await restore_text(req)
    return res
