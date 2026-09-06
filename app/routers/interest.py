import uuid
from decimal import Decimal
from datetime import date
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter
from app.db import db

router = APIRouter()

class InterestRunRequest(BaseModel):
    period_start: date
    period_end: date

class InterestResult(BaseModel):
    account_id: str
    skipped: bool
    skip_reason: str
    rate_applied: Decimal
    amount_credited: Decimal
    transaction_id: Optional[str]

class InterestRunResponse(BaseModel):
    request_id: str
    results: List[InterestResult]

@router.post("/run", response_model=InterestRunResponse)
async def run_interest(req: InterestRunRequest):
    req_id = str(uuid.uuid4())
    results = []
    
    days_in_period = Decimal((req.period_end - req.period_start).days)
    if days_in_period <= 0:
        days_in_period = Decimal("1")
        
    async with db.pool.acquire() as conn:
        accounts = await conn.fetch("""
            SELECT id, balance, status, interest_rate 
            FROM accounts 
            WHERE interest_rate > 0
        """)
        
        for acc in accounts:
            acc_id = acc['id']
            balance = Decimal(str(acc['balance']))
            status = acc['status']
            rate = Decimal(str(acc['interest_rate']))
            
            already = await conn.fetchrow("""
                SELECT id FROM interest_accrual_log 
                WHERE account_id = $1 AND period_start = $2
            """, acc_id, req.period_start)
            
            if already:
                results.append(InterestResult(
                    account_id=str(acc_id), skipped=True, skip_reason="NONE",
                    rate_applied=rate, amount_credited=Decimal("0"), transaction_id=None
                ))
                continue
                
            skip_reason = None
            if balance < 0:
                skip_reason = "NEGATIVE_BALANCE"
            elif status == "SUSPENDED":
                skip_reason = "SUSPENDED"
            elif status == "CLOSED":
                skip_reason = "ACCOUNT_CLOSED"
                
            if skip_reason:
                await conn.execute("""
                    INSERT INTO interest_accrual_log 
                    (account_id, period_start, period_end, rate_applied, amount_credited, skipped, skip_reason)
                    VALUES ($1, $2, $3, $4, 0, true, $5)
                """, acc_id, req.period_start, req.period_end, rate, skip_reason)
                
                results.append(InterestResult(
                    account_id=str(acc_id), skipped=True, skip_reason=skip_reason,
                    rate_applied=rate, amount_credited=Decimal("0"), transaction_id=None
                ))
                continue
                
            amount_credited = round(balance * rate * (days_in_period / Decimal("365")), 2)
            idem_key = f"interest-{acc_id}-{req.period_start}"
            
            async with conn.transaction():
                txn_id = await conn.fetchval("""
                    INSERT INTO transactions 
                    (account_id, amount, type, status, idempotency_key, description)
                    VALUES ($1, $2, 'INTEREST', 'COMPLETED', $3, 'Interest accrual')
                    RETURNING id
                """, acc_id, amount_credited, idem_key)
                
                await conn.execute("""
                    UPDATE accounts SET balance = balance + $1 WHERE id = $2
                """, amount_credited, acc_id)
                
                await conn.execute("""
                    INSERT INTO interest_accrual_log 
                    (account_id, period_start, period_end, rate_applied, amount_credited, transaction_id, skipped, skip_reason)
                    VALUES ($1, $2, $3, $4, $5, $6, false, 'NONE')
                """, acc_id, req.period_start, req.period_end, rate, amount_credited, txn_id)
                
            results.append(InterestResult(
                account_id=str(acc_id), skipped=False, skip_reason="NONE",
                rate_applied=rate, amount_credited=amount_credited, transaction_id=str(txn_id)
            ))
            
    return InterestRunResponse(request_id=req_id, results=results)
