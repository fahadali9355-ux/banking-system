import uuid
import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.db import db
import hashlib

async def execute_transfer(req):
    async with db.pool.acquire() as conn:
        idem = await conn.fetchrow("""
            SELECT response_payload FROM idempotency_keys WHERE key = $1
        """, req.idempotency_key)
        
        if idem:
            payload = json.loads(idem['response_payload'])
            return payload, 409
            
        req_id = req.idempotency_key
        try:
            async with conn.transaction():
                sender_acc = await conn.fetchrow("""
                    SELECT balance, status FROM accounts WHERE id = $1::uuid FOR UPDATE
                """, req.from_account_id)
                
                if not sender_acc:
                    return {"request_id": req_id, "status": "ROLLED_BACK", "reason": "Sender account not found"}, 404
                    
                amount = Decimal(req.amount)
                
                if sender_acc['balance'] < amount:
                    return {"request_id": req_id, "status": "ROLLED_BACK", "reason": "Insufficient funds"}, 402
                
                receiver_acc = await conn.fetchrow("""
                    SELECT balance, status FROM accounts WHERE id = $1::uuid FOR UPDATE
                """, req.to_account_id)
                
                if not receiver_acc:
                    return {"request_id": req_id, "status": "ROLLED_BACK", "reason": "Receiver account not found"}, 404
                
                new_sender_balance = sender_acc['balance'] - amount
                new_receiver_balance = receiver_acc['balance'] + amount
                
                await conn.execute("UPDATE accounts SET balance = $1 WHERE id = $2::uuid", new_sender_balance, req.from_account_id)
                await conn.execute("UPDATE accounts SET balance = $1 WHERE id = $2::uuid", new_receiver_balance, req.to_account_id)
                
                sender_tx_id = str(uuid.uuid4())
                receiver_tx_id = str(uuid.uuid4())
                
                await conn.execute("""
                    INSERT INTO transactions (id, account_id, amount, type, status, idempotency_key, description)
                    VALUES ($1::uuid, $2::uuid, $3, 'TRANSFER_OUT', 'COMPLETED', $4, $5)
                """, sender_tx_id, req.from_account_id, amount, req.idempotency_key, req.description)
                
                await conn.execute("""
                    INSERT INTO transactions (id, account_id, amount, type, status, idempotency_key, description)
                    VALUES ($1::uuid, $2::uuid, $3, 'TRANSFER_IN', 'COMPLETED', $4, $5)
                """, receiver_tx_id, req.to_account_id, amount, req.idempotency_key + "_in", req.description)
                
                res_payload = {
                    "request_id": req_id,
                    "status": "COMPLETED",
                    "transaction_id": sender_tx_id,
                    "new_balance": str(new_sender_balance)
                }
                
                req_hash = hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()
                await conn.execute("""
                    INSERT INTO idempotency_keys (key, request_hash, response_payload)
                    VALUES ($1, $2, $3)
                """, req.idempotency_key, req_hash, json.dumps(res_payload))
                
                return res_payload, 200
        except Exception as e:
            return {"request_id": req_id, "status": "ROLLED_BACK", "reason": str(e)}, 500

async def reverse_transaction(req):
    req_id = str(uuid.uuid4())
    async with db.pool.acquire() as conn:
        try:
            async with conn.transaction():
                orig_tx = await conn.fetchrow("""
                    SELECT id, account_id, amount, type FROM transactions WHERE id = $1::uuid FOR UPDATE
                """, req.original_transaction_id)
                
                if not orig_tx:
                    return {"request_id": req_id, "reversal_transaction_id": "", "new_balance": "0"}, 404
                    
                existing_rev = await conn.fetchrow("""
                    SELECT id FROM transactions WHERE related_transaction_id = $1::uuid
                """, req.original_transaction_id)
                
                if existing_rev:
                    return {"request_id": req_id, "reversal_transaction_id": "", "new_balance": "0"}, 409
                    
                acc = await conn.fetchrow("""
                    SELECT balance FROM accounts WHERE id = $1::uuid FOR UPDATE
                """, orig_tx['account_id'])
                
                amount = orig_tx['amount']
                is_credit_reversal = orig_tx['type'] in ('DEBIT', 'TRANSFER_OUT')
                
                if is_credit_reversal:
                    new_balance = acc['balance'] + amount
                else:
                    new_balance = acc['balance'] - amount
                    
                await conn.execute("UPDATE accounts SET balance = $1 WHERE id = $2::uuid", new_balance, orig_tx['account_id'])
                
                rev_tx_id = str(uuid.uuid4())
                idem_key = "rev_" + str(req.original_transaction_id)
                await conn.execute("""
                    INSERT INTO transactions (id, account_id, related_transaction_id, amount, type, status, idempotency_key, description)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, 'REVERSAL', 'COMPLETED', $5, $6)
                """, rev_tx_id, orig_tx['account_id'], orig_tx['id'], amount, idem_key, req.reason)
                
                return {
                    "request_id": req_id,
                    "reversal_transaction_id": rev_tx_id,
                    "new_balance": str(new_balance)
                }, 200
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

async def create_approval_request(req):
    req_id = str(uuid.uuid4())
    async with db.pool.acquire() as conn:
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        row = await conn.fetchrow("""
            INSERT INTO transaction_approval_requests (account_id, idempotency_key, initiated_by, expires_at)
            VALUES ($1::uuid, $2, $3::uuid, $4)
            RETURNING id
        """, req.account_id, req.idempotency_key, req.initiated_by, expires_at)
        
        return {
            "request_id": req_id,
            "approval_request_id": str(row['id']),
            "expires_at": expires_at
        }

async def resolve_approval(req):
    req_id = str(uuid.uuid4())
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, account_id, approvals, expires_at FROM transaction_approval_requests WHERE id = $1::uuid FOR UPDATE
        """, req.approval_request_id)
        
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
            
        if datetime.now(timezone.utc) > row['expires_at'].replace(tzinfo=timezone.utc):
            await conn.execute("UPDATE transaction_approval_requests SET status = 'ESCALATED' WHERE id = $1::uuid", req.approval_request_id)
            return {"request_id": req_id, "status": "ESCALATED", "ready_to_execute": False}, 410
            
        approvals = json.loads(row['approvals']) if isinstance(row['approvals'], str) else dict(row['approvals']) if row['approvals'] else {}
        approvals[req.holder_id] = (req.decision == 'APPROVED')
        
        holders_count = await conn.fetchval("""
            SELECT count(*) FROM account_holders WHERE account_id = $1::uuid AND status = 'ACTIVE'
        """, row['account_id'])
        
        all_approved = len(approvals) == holders_count and all(approvals.values())
        status = 'APPROVED' if all_approved else 'PENDING'
        
        await conn.execute("""
            UPDATE transaction_approval_requests SET approvals = $1, status = $2::closure_status_enum WHERE id = $3::uuid
        """, json.dumps(approvals), status, req.approval_request_id)
        
        return {
            "request_id": req_id,
            "status": status,
            "ready_to_execute": all_approved
        }, 200
