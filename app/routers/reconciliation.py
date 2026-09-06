import uuid
from decimal import Decimal
from typing import List
from pydantic import BaseModel
from fastapi import APIRouter
from app.db import db

router = APIRouter()

class Mismatch(BaseModel):
    account_id: str
    ledger_sum: Decimal
    reported_balance: Decimal
    discrepancy: Decimal
    likely_cause: str

class ReconciliationResponse(BaseModel):
    request_id: str
    mismatches: List[Mismatch]

@router.post("/run", response_model=ReconciliationResponse)
async def run_reconciliation():
    req_id = str(uuid.uuid4())
    mismatches = []
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.id as account_id, a.balance as reported_balance, 
                   COALESCE(SUM(t.amount), 0) as ledger_sum
            FROM accounts a
            LEFT JOIN transactions t ON a.id = t.account_id AND t.status = 'COMPLETED'
            GROUP BY a.id, a.balance
        """)
        
        for row in rows:
            reported = Decimal(str(row['reported_balance']))
            ledger = Decimal(str(row['ledger_sum']))
            
            if reported != ledger:
                discrepancy = reported - ledger
                
                abs_disc = abs(discrepancy)
                if abs_disc < Decimal("1.00"):
                    likely_cause = "ROUNDING_ERROR"
                else:
                    dup_check = await conn.fetchval("""
                        SELECT COUNT(*) FROM transactions 
                        WHERE account_id = $1 AND amount = $2 AND status = 'COMPLETED'
                    """, row['account_id'], discrepancy)
                    if dup_check and dup_check > 1:
                        likely_cause = "DUPLICATE_ENTRY"
                    else:
                        likely_cause = "UNKNOWN"
                        
                mismatches.append(Mismatch(
                    account_id=str(row['account_id']),
                    ledger_sum=ledger,
                    reported_balance=reported,
                    discrepancy=discrepancy,
                    likely_cause=likely_cause
                ))
                
    return ReconciliationResponse(request_id=req_id, mismatches=mismatches)
