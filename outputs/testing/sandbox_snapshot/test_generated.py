import pytest
from target_app.service import AccountService
from fastapi.testclient import TestClient
from target_app.main import app

client = TestClient(app)
service = AccountService()

def test_register_a_new_account():
    account_data = {
        "id": "123",
        "name": "John Doe",
        "age": 25,
        "type": "STANDARD",
        "opening": 100.0
    }
    result = service.register_account(account_data)
    assert result == "Account successfully registered"

def test_activate_an_account():
    account_id = "123"
    result = service.activate_account(account_id)
    assert result == "Account successfully activated"

def test_suspend_an_account():
    account_id = "123"
    reason = "Fraudulent activity"
    result = service.suspend_account(account_id, reason)
    assert result == "Account successfully suspended"

def test_close_an_account():
    account_id = "123"
    result = service.close_account(account_id)
    assert result == "Account successfully closed"

def test_deposit_into_an_account():
    account_id = "123"
    amount = 500.0
    result = service.deposit(account_id, amount)
    assert result == "Deposit successful"

def test_withdraw_from_an_account():
    account_id = "123"
    amount = 100.0
    result = service.withdraw(account_id, amount)
    assert result == "Withdrawal successful"

def test_transfer_between_accounts():
    source_id = "123"
    destination_id = "456"
    amount = 1000.0
    result = service.transfer(source_id, destination_id, amount)
    assert result == "Transfer successful"

def test_handle_invalid_account_type_during_registration():
    account_data = {
        "id": "123",
        "name": "John Doe",
        "age": 25,
        "type": "INVALID_TYPE",
        "opening": 100.0
    }
    with pytest.raises(ValueError, match="INVALID_ACCOUNT_TYPE"):
        service.register_account(account_data)

def test_handle_account_registration_for_underage_customers():
    account_data = {
        "id": "123",
        "name": "John Doe",
        "age": 17,
        "type": "STANDARD",
        "opening": 100.0
    }
    with pytest.raises(ValueError, match="UNDERAGE_CUSTOMER"):
        service.register_account(account_data)

def test_handle_negative_opening_balance_during_registration():
    account_data = {
        "id": "123",
        "name": "John Doe",
        "age": 25,
        "type": "STANDARD",
        "opening": -100.0
    }
    with pytest.raises(ValueError, match="INVALID_OPENING_BALANCE"):
        service.register_account(account_data)
