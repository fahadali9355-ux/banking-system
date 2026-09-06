from fastapi import APIRouter
from app.models.auth import (
    VerifyPasswordRequest, VerifyPasswordResponse,
    VerifyOtpRequest, VerifyOtpResponse,
    IssueChallengeCodeRequest, IssueChallengeCodeResponse
)
from app.services.auth import (
    verify_password,
    verify_otp,
    issue_challenge_code
)

router = APIRouter()

@router.post("/verify-password", response_model=VerifyPasswordResponse)
async def verify_password_endpoint(req: VerifyPasswordRequest):
    return await verify_password(req)

@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp_endpoint(req: VerifyOtpRequest):
    return await verify_otp(req)

@router.post("/issue-challenge-code", response_model=IssueChallengeCodeResponse)
async def issue_challenge_code_endpoint(req: IssueChallengeCodeRequest):
    return await issue_challenge_code(req)
