import uuid
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db

router = APIRouter()

class ReactivationVerifyRequest(BaseModel):
    reactivation_request_id: str
    full_name: str
    date_of_birth: date
    last_transaction_amount: Decimal

class ReactivationVerifyResponse(BaseModel):
    request_id: str
    passed: bool

@router.post("/verify-identity", response_model=ReactivationVerifyResponse)
async def verify_identity(req: ReactivationVerifyRequest):
    req_id = str(uuid.uuid4())
    
    async with db.pool.acquire() as conn:
        req_row = await conn.fetchrow("SELECT account_id FROM reactivation_requests WHERE id = $1::uuid", req.reactivation_request_id)
        if not req_row:
            raise HTTPException(status_code=404, detail="Reactivation request not found")
            
        account_id = req_row['account_id']
        
        holders = await conn.fetch("""
            SELECT u.full_name, u.date_of_birth 
            FROM users u
            JOIN account_holders ah ON ah.user_id = u.id
            WHERE ah.account_id = $1::uuid
        """, account_id)
        
        name_dob_match = False
        for h in holders:
            if h['full_name'].lower() == req.full_name.lower() and h['date_of_birth'] == req.date_of_birth:
                name_dob_match = True
                break
                
        last_txn = await conn.fetchrow("""
            SELECT amount FROM transactions
            WHERE account_id = $1::uuid AND status = 'COMPLETED'
            ORDER BY created_at DESC LIMIT 1
        """, account_id)
        
        last_txn_match = False
        if last_txn and Decimal(str(last_txn['amount'])) == req.last_transaction_amount:
            last_txn_match = True
            
        passed = name_dob_match and last_txn_match
        
        if passed:
            await conn.execute("""
                UPDATE reactivation_requests SET identity_challenge_passed = true 
                WHERE id = $1::uuid
            """, req.reactivation_request_id)
            
    return ReactivationVerifyResponse(request_id=req_id, passed=passed)
