from fastapi import APIRouter
from app.models.fraud import FraudScoreRequest, FraudScoreResponse
from app.services.fraud import score_transaction

router = APIRouter()

@router.post("/score", response_model=FraudScoreResponse)
async def score_transaction_endpoint(req: FraudScoreRequest):
    res = await score_transaction(req)
    return res
