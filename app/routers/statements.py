from fastapi import APIRouter
from app.models.statements import StatementRequest, StatementResponse
from app.services.statements import generate_statement

router = APIRouter()

@router.post("/generate", response_model=StatementResponse)
async def generate_statement_endpoint(req: StatementRequest):
    res = await generate_statement(req)
    return res
