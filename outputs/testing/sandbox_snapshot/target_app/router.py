from fastapi import APIRouter, HTTPException
from .schemas import (
    RegisterAccountRequest,
    ActivateAccountRequest,
    SuspendAccountRequest,
    CloseAccountRequest,
    DepositRequest,
    WithdrawRequest,
    TransferRequest
)
from .service import AccountService

router = APIRouter()

service = AccountService()

@router.post("/registerAccount", response_model=str, status_code=200)
async def register_account(request: RegisterAccountRequest):
    try:
        return service.register_account(request.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/activateAccount", response_model=str, status_code=200)
async def activate_account(request: ActivateAccountRequest):
    try:
        return service.activate_account(request.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/suspendAccount", response_model=str, status_code=200)
async def suspend_account(request: SuspendAccountRequest):
    try:
        return service.suspend_account(request.id, request.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/closeAccount", response_model=str, status_code=200)
async def close_account(request: CloseAccountRequest):
    try:
        return service.close_account(request.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/deposit", response_model=str, status_code=200)
async def deposit(request: DepositRequest):
    try:
        return service.deposit(request.id, request.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/withdraw", response_model=str, status_code=200)
async def withdraw(request: WithdrawRequest):
    try:
        return service.withdraw(request.id, request.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/transfer", response_model=str, status_code=200)
async def transfer(request: TransferRequest):
    try:
        return service.transfer(request.sourceId, request.destinationId, request.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
