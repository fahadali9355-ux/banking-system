import uuid
import os
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from app.db import db

async def score_transaction(req):
    req_id = str(uuid.uuid4())
    
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT amount FROM transactions 
            WHERE account_id = $1::uuid AND created_at >= $2
        """, req.account_id, ninety_days_ago)
        
    amount = Decimal(req.amount)
    
    if len(rows) > 0:
        total = sum(row['amount'] for row in rows)
        avg_amount = total / len(rows)
        
        if avg_amount > 0 and amount > avg_amount * 3:
            ratio = amount / avg_amount
            rule_score = 0.82
            rule_reason = f"{ratio:.1f}x this account's 90-day average spend"
        else:
            rule_score = 0.10
            rule_reason = "Within normal 90-day spending pattern"
    else:
        if amount > 3000.00:
            rule_score = 0.80
            rule_reason = "High amount with no prior history"
        else:
            rule_score = 0.20
            rule_reason = "Normal amount with no prior history"
            
    pattern_match = {
        "matched": False,
        "pinecone_match_id": None,
        "similarity_score": None,
        "summary": None
    }
    
    pinecone_key = os.environ.get("PINECONE_API_KEY")
    if pinecone_key:
        try:
            from pinecone import Pinecone
            pc = Pinecone(api_key=pinecone_key)
            
            # For the hackathon, we'll try to connect to 'fraud-patterns'
            # If it fails or doesn't exist, we fall back.
            # Replace this with actual embedding/query logic if needed.
            # pattern_match["matched"] = True
            # pattern_match["pinecone_match_id"] = "fp_004821"
            # pattern_match["similarity_score"] = 0.87
            # pattern_match["summary"] = "Similar to a confirmed card-testing pattern from 2026-03"
        except Exception:
            pass
            
    combined_score = rule_score
    if pattern_match["matched"] and pattern_match["similarity_score"] is not None:
        combined_score = (rule_score + pattern_match["similarity_score"]) / 2.0
        
    flag = False
    if combined_score >= 0.7 or rule_score >= 0.8:
        flag = True
        
    return {
        "request_id": req_id,
        "rule_score": round(float(rule_score), 2),
        "rule_reason": rule_reason,
        "pattern_match": pattern_match,
        "combined_score": round(float(combined_score), 2),
        "flag": flag
    }
