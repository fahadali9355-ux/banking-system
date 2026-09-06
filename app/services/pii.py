import uuid
import re
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

# In-memory token store for the hackathon
token_maps = {}

async def redact_text(req):
    req_id = str(uuid.uuid4())
    token_map_id = f"tm_{uuid.uuid4().hex[:8]}"
    
    current_map = {}
    text = req.text
    
    amount_pattern = r'(?:\$|Rs\.?)\s*\d+(?:\.\d{1,2})?|\b\d+\.\d{2}\b'
    acc_pattern = r'\b\d{6,}\b'
    # Simplified name detection heuristic for the hackathon
    name_pattern = r'(?<!^)(?<!\.\s)(?<!\?\s)(?<!\!\s)\b[A-Z][a-z]+\b'
    
    amount_count = 1
    acc_count = 1
    name_count = 1
    
    amounts = list(set(re.findall(amount_pattern, text)))
    for val in amounts:
        token = f"AMOUNT_TOKEN_{amount_count}"
        current_map[token] = val
        text = text.replace(val, token)
        amount_count += 1
        
    accs = list(set(re.findall(acc_pattern, text)))
    for val in accs:
        token = f"ACC_TOKEN_{acc_count}"
        current_map[token] = val
        text = text.replace(val, token)
        acc_count += 1
        
    # NOTE: Name detection is a simplified heuristic for the hackathon, not production-grade NER.
    names = list(set(re.findall(name_pattern, text)))
    for val in names:
        if val not in ["The", "A", "An", "In", "On", "At", "Please"]:
            token = f"NAME_TOKEN_{name_count}"
            current_map[token] = val
            text = text.replace(val, token)
            name_count += 1
            
    token_maps[token_map_id] = {
        "created_at": datetime.now(timezone.utc),
        "mapping": current_map
    }
    
    return {
        "request_id": req_id,
        "redacted_text": text,
        "token_map_id": token_map_id
    }

async def restore_text(req):
    req_id = str(uuid.uuid4())
    
    map_data = token_maps.get(req.token_map_id)
    if not map_data:
        raise HTTPException(status_code=410, detail="token_map_id expired or not found")
        
    if datetime.now(timezone.utc) - map_data["created_at"] > timedelta(hours=1):
        del token_maps[req.token_map_id]
        raise HTTPException(status_code=410, detail="token_map_id expired")
        
    text = req.text
    for token, real_val in map_data["mapping"].items():
        text = text.replace(token, real_val)
        
    return {
        "request_id": req_id,
        "restored_text": text
    }
