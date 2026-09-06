import uuid
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from app.db import db

router = APIRouter()

class BalanceCheckRequest(BaseModel):
    account_id: str
    amount: Decimal

class BalanceCheckResponse(BaseModel):
    request_id: str
    sufficient: bool
    current_balance: Decimal

class StandingOrderExecuteRequest(BaseModel):
    standing_order_id: str
    expected_version: int

class StandingOrderExecuteResponse(BaseModel):
    request_id: str
    executed: bool
    new_version: int
    transaction_id: Optional[str]

@router.post("/balance-check", response_model=BalanceCheckResponse)
async def balance_check(req: BalanceCheckRequest):
    req_id = str(uuid.uuid4())
    async with db.pool.acquire() as conn:
        acc = await conn.fetchrow("SELECT balance FROM accounts WHERE id = $1::uuid", req.account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found")
        balance = Decimal(str(acc['balance']))
        
    return BalanceCheckResponse(
        request_id=req_id,
        sufficient=balance >= req.amount,
        current_balance=balance
    )

@router.post("/execute", response_model=StandingOrderExecuteResponse)
async def execute_standing_order(req: StandingOrderExecuteRequest, response: Response):
    req_id = str(uuid.uuid4())
    
    async with db.pool.acquire() as conn:
        so = await conn.fetchrow("""
            SELECT account_id, beneficiary_account_id, amount, version 
            FROM standing_orders WHERE id = $1::uuid
        """, req.standing_order_id)
        
        if not so:
            raise HTTPException(status_code=404, detail="Standing order not found")
            
        if so['version'] != req.expected_version:
            raise HTTPException(status_code=409, detail=f"Version mismatch. Current version is {so['version']}")
            
        account_id = so['account_id']
        beneficiary = so['beneficiary_account_id']
        amount = Decimal(str(so['amount']))
        new_version = so['version'] + 1
        
        acc = await conn.fetchrow("SELECT balance FROM accounts WHERE id = $1::uuid", account_id)
        balance = Decimal(str(acc['balance']))
        
        if balance < amount:
            await conn.execute("""
                INSERT INTO standing_order_attempts (standing_order_id, result) 
                VALUES ($1::uuid, 'INSUFFICIENT_FUNDS')
            """, req.standing_order_id)
            return StandingOrderExecuteResponse(
                request_id=req_id, executed=False, new_version=so['version'], transaction_id=None
            )
            
        idem_key = f"so-{req.standing_order_id}-{new_version}-{uuid.uuid4()}"
        async with conn.transaction():
            txn_out = await conn.fetchval("""
                INSERT INTO transactions (account_id, amount, type, status, idempotency_key, description)
                VALUES ($1, $2, 'TRANSFER_OUT', 'COMPLETED', $3, 'Standing order OUT') RETURNING id
            """, account_id, amount, idem_key + "-out")
            
            if beneficiary:
                await conn.execute("""
                    INSERT INTO transactions (account_id, amount, type, status, idempotency_key, description)
                    VALUES ($1, $2, 'TRANSFER_IN', 'COMPLETED', $3, 'Standing order IN')
                """, beneficiary, amount, idem_key + "-in")
                await conn.execute("UPDATE accounts SET balance = balance + $1 WHERE id = $2::uuid", amount, beneficiary)
                
            await conn.execute("UPDATE accounts SET balance = balance - $1 WHERE id = $2::uuid", amount, account_id)
            
            await conn.execute("UPDATE standing_orders SET version = $1 WHERE id = $2::uuid", new_version, req.standing_order_id)
            
            await conn.execute("""
                INSERT INTO standing_order_attempts (standing_order_id, result) 
                VALUES ($1::uuid, 'SUCCESS')
            """, req.standing_order_id)
            
    return StandingOrderExecuteResponse(
        request_id=req_id, executed=True, new_version=new_version, transaction_id=str(txn_out)
    )
