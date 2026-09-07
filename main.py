"""
Digital Banking Ops Automation — Python Services
Covers feature-list item #31: Python services for interest calculation,
fraud scoring, and reconciliation.

Actual call direction per endpoint (this matters — it's not the same for all three):
  - /reconciliation-check : called BY n8n (Branch A, "HTTP: Reconciliation
    Check (Python Service)" node) once per account, every night. This is a
    real HTTP Request node in the workflow, not just documented intent.
  - /fraud-score : NOT called by n8n. This is meant to run inside the
    external fraud-scoring service that itself POSTs the resulting score
    to n8n's "Webhook: Fraud Score Event" (Branch C). Kept here so the
    scoring logic has one canonical, testable implementation even though
    n8n never calls this endpoint directly.
  - /interest-calc : standalone utility, not wired into any branch yet.
    Available if a future statement/interest-accrual job is added.

Set PYTHON_SERVICE_URL as an n8n environment variable to this service's
public URL (e.g. your ngrok/Render URL) before running Branch A live.

Run: uvicorn main:app --host 0.0.0.0 --port 8000
Expose to n8n cloud with ngrok: ngrok http 8000
"""

from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional

app = FastAPI(title="Banking Ops Python Services")


# ---------------------------------------------------------------------------
# 1. FRAUD SCORING  (feeds Branch C: fraud-flag webhook in n8n)
# ---------------------------------------------------------------------------
class FraudScoreRequest(BaseModel):
    account_id: str
    transaction_id: str
    amount: float
    account_avg_transaction: float
    tx_count_last_hour: int
    is_new_payee: bool
    country_mismatch: bool


class FraudScoreResponse(BaseModel):
    account_id: str
    transaction_id: str
    score: float
    reason: str
    should_hold: bool


@app.post("/fraud-score", response_model=FraudScoreResponse)
def fraud_score(req: FraudScoreRequest):
    """
    Weighted heuristic fraud score in [0, 1]. Each signal contributes a
    bounded weight so no single factor can force a hold on its own except
    a very large amount deviation combined with velocity — mirrors how a
    real rules-engine avoids single-signal false positives.
    """
    score = 0.0
    reasons = []

    # Amount deviation from the account's own historical average
    if req.account_avg_transaction > 0:
        deviation = req.amount / req.account_avg_transaction
        if deviation > 5:
            score += 0.40
            reasons.append(f"amount {deviation:.1f}x account average")
        elif deviation > 3:
            score += 0.20
            reasons.append(f"amount {deviation:.1f}x account average")

    # Velocity: many transactions in a short window
    if req.tx_count_last_hour >= 5:
        score += 0.25
        reasons.append(f"{req.tx_count_last_hour} transactions in last hour")
    elif req.tx_count_last_hour >= 3:
        score += 0.10

    # New, never-seen payee
    if req.is_new_payee:
        score += 0.15
        reasons.append("first-time payee")

    # Geo mismatch (card-present-style signal)
    if req.country_mismatch:
        score += 0.25
        reasons.append("country mismatch vs account home country")

    score = min(score, 1.0)

    return FraudScoreResponse(
        account_id=req.account_id,
        transaction_id=req.transaction_id,
        score=round(score, 2),
        reason="; ".join(reasons) if reasons else "no anomaly signals",
        should_hold=score >= 0.60,  # threshold matches Branch C's auto-hold trigger
    )


# ---------------------------------------------------------------------------
# 2. INTEREST CALCULATION  (feeds statements / nightly interest accrual job)
# ---------------------------------------------------------------------------
class InterestRequest(BaseModel):
    principal: float
    annual_rate_percent: float
    days: int
    compounding: str = "daily"  # "daily" | "simple"


class InterestResponse(BaseModel):
    principal: float
    interest_earned: float
    new_balance: float


@app.post("/interest-calc", response_model=InterestResponse)
def interest_calc(req: InterestRequest):
    rate = req.annual_rate_percent / 100.0
    if req.compounding == "simple":
        interest = req.principal * rate * (req.days / 365.0)
    else:
        daily_rate = rate / 365.0
        interest = req.principal * ((1 + daily_rate) ** req.days - 1)

    interest = round(interest, 2)
    return InterestResponse(
        principal=req.principal,
        interest_earned=interest,
        new_balance=round(req.principal + interest, 2),
    )


# ---------------------------------------------------------------------------
# 3. RECONCILIATION CHECK  (feeds Branch A: nightly reconciliation in n8n)
# ---------------------------------------------------------------------------
class ReconciliationRequest(BaseModel):
    account_id: str
    ledger_sum: float
    reported_balance: float


class ReconciliationResponse(BaseModel):
    account_id: str
    mismatch: bool
    difference: float


@app.post("/reconciliation-check", response_model=ReconciliationResponse)
def reconciliation_check(req: ReconciliationRequest):
    diff = round(req.ledger_sum - req.reported_balance, 2)
    return ReconciliationResponse(
        account_id=req.account_id,
        mismatch=abs(diff) > 0.01,
        difference=diff,
    )


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
