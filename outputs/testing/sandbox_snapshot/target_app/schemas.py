from pydantic import BaseModel, Field
from typing import Literal

class RegisterAccountRequest(BaseModel):
    id: str
    name: str
    age: int
    type: Literal['STANDARD', 'PREMIUM', 'STUDENT']
    opening: float = Field(..., ge=0)

class ActivateAccountRequest(BaseModel):
    id: str

class SuspendAccountRequest(BaseModel):
    id: str
    reason: str

class CloseAccountRequest(BaseModel):
    id: str

class DepositRequest(BaseModel):
    id: str
    amount: float = Field(..., ge=0.01, le=100000.0)

class WithdrawRequest(BaseModel):
    id: str
    amount: float = Field(..., ge=0.01)

class TransferRequest(BaseModel):
    sourceId: str
    destinationId: str
    amount: float = Field(..., ge=1.0, le=5000.0)
