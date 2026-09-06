from pydantic import BaseModel
from typing import Optional

class PatternMatch(BaseModel):
    matched: bool
    pinecone_match_id: Optional[str] = None
    similarity_score: Optional[float] = None
    summary: Optional[str] = None

class FraudScoreRequest(BaseModel):
    transaction_id: str
    account_id: str
    amount: str

class FraudScoreResponse(BaseModel):
    request_id: str
    rule_score: float
    rule_reason: str
    pattern_match: PatternMatch
    combined_score: float
    flag: bool
