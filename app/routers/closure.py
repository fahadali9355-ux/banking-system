import uuid
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db
from decimal import Decimal

router = APIRouter()

class ClosureExecuteRequest(BaseModel):
    closure_request_id: str
    account_id: str

class ClosureExecuteResponse(BaseModel):
    request_id: str
    account_status: str
    final_statement_url: str

@router.post("/execute", response_model=ClosureExecuteResponse)
async def execute_closure(req: ClosureExecuteRequest):
    req_id = str(uuid.uuid4())
    
    async with db.pool.acquire() as conn:
        closure_req = await conn.fetchrow("""
            SELECT approvals FROM account_closure_requests 
            WHERE id = $1::uuid AND account_id = $2::uuid
        """, req.closure_request_id, req.account_id)
        
        if not closure_req:
            raise HTTPException(status_code=404, detail="Closure request not found")
            
        approvals = json.loads(closure_req['approvals'])
        
        holders = await conn.fetch("""
            SELECT id FROM account_holders WHERE account_id = $1::uuid
        """, req.account_id)
        
        if not holders:
            raise HTTPException(status_code=404, detail="Account holders not found")
            
        for holder in holders:
            hid = str(holder['id'])
            val = approvals.get(hid)
            if str(val).lower() != "true" and val is not True:
                raise HTTPException(status_code=409, detail="Not all account holders have approved closure")
                
        acc = await conn.fetchrow("SELECT balance FROM accounts WHERE id = $1::uuid", req.account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found")
            
        balance = Decimal(str(acc['balance']))
        if balance != Decimal("0"):
            raise HTTPException(status_code=422, detail="Account balance must be 0 to close (payout instructions not yet supported)")
            
        async with conn.transaction():
            await conn.execute("UPDATE accounts SET status = 'CLOSED' WHERE id = $1::uuid", req.account_id)
            await conn.execute("""
                UPDATE account_closure_requests 
                SET status = 'APPROVED', resolved_at = now() 
                WHERE id = $1::uuid
            """, req.closure_request_id)
            
    return ClosureExecuteResponse(
        request_id=req_id,
        account_status="CLOSED",
        final_statement_url=f"/statements/final_{req.account_id}.pdf"
    )
