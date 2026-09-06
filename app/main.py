from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import db
from app.routers import (
    auth, transactions, fraud, statements, pii,
    reconciliation, interest, closure, standing_orders, reactivation
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()

app = FastAPI(lifespan=lifespan, title="Digital Banking Backend")

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
app.include_router(fraud.router, prefix="/fraud", tags=["Fraud"])
app.include_router(statements.router, prefix="/statements", tags=["Statements"])
app.include_router(pii.router, prefix="/pii", tags=["PII"])
app.include_router(reconciliation.router, prefix="/reconciliation", tags=["Reconciliation"])
app.include_router(interest.router, prefix="/interest", tags=["Interest"])
app.include_router(closure.router, prefix="/closure", tags=["Closure"])
app.include_router(standing_orders.router, prefix="/standing-orders", tags=["Standing Orders"])
app.include_router(reactivation.router, prefix="/reactivation", tags=["Reactivation"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}
