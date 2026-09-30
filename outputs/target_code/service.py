from typing import Dict, Union

class AccountService:
    """
    Service layer for managing account lifecycle operations.
    """

    def register_account(self, account_data: Dict[str, Union[str, int, float]]) -> str:
        """
        Register a new account.

        Args:
            account_data: A dictionary containing account details (id, name, age, type, opening balance).

        Returns:
            A confirmation message if registration is successful.

        Raises:
            ValueError: If account type is invalid, age is below 18, or opening balance is negative.
        """
        valid_account_types = {"STANDARD", "PREMIUM", "STUDENT"}

        if account_data["type"] not in valid_account_types:
            raise ValueError("INVALID_ACCOUNT_TYPE")

        if account_data["age"] < 18:
            raise ValueError("UNDERAGE_CUSTOMER")

        if account_data["opening"] < 0:
            raise ValueError("INVALID_OPENING_BALANCE")

        # Simulate account registration logic
        return "Account successfully registered"

    def activate_account(self, account_id: str) -> str:
        """
        Activate an account.

        Args:
            account_id: The ID of the account to activate.

        Returns:
            A confirmation message if activation is successful.

        Raises:
            ValueError: If the account ID is invalid.
        """
        # Simulate account activation logic
        return "Account successfully activated"

    def suspend_account(self, account_id: str, reason: str) -> str:
        """
        Suspend an account.

        Args:
            account_id: The ID of the account to suspend.
            reason: The reason for suspending the account.

        Returns:
            A confirmation message if suspension is successful.

        Raises:
            ValueError: If input data is invalid.
        """
        # Simulate account suspension logic
        return "Account successfully suspended"

    def close_account(self, account_id: str) -> str:
        """
        Close an account.

        Args:
            account_id: The ID of the account to close.

        Returns:
            A confirmation message if closure is successful.

        Raises:
            ValueError: If the account ID is invalid.
        """
        # Simulate account closure logic
        return "Account successfully closed"

    def deposit(self, account_id: str, amount: float) -> str:
        """
        Deposit an amount into an account.

        Args:
            account_id: The ID of the account to deposit into.
            amount: The amount to deposit (must be positive and <= 100,000.00).

        Returns:
            A confirmation message if deposit is successful.

        Raises:
            ValueError: If the deposit amount is invalid.
        """
        if not (0.01 <= amount <= 100000.0):
            raise ValueError("Invalid deposit amount")

        # Simulate deposit logic
        return "Deposit successful"

    def withdraw(self, account_id: str, amount: float) -> str:
        """
        Withdraw an amount from an account.

        Args:
            account_id: The ID of the account to withdraw from.
            amount: The amount to withdraw (must be positive).

        Returns:
            A confirmation message if withdrawal is successful.

        Raises:
            ValueError: If the withdrawal amount is invalid or balance is insufficient.
        """
        if amount <= 0:
            raise ValueError("Invalid withdrawal amount")

        # Simulate withdrawal logic
        return "Withdrawal successful"

    def transfer(self, source_id: str, destination_id: str, amount: float) -> str:
        """
        Transfer an amount between two accounts.

        Args:
            source_id: The ID of the source account.
            destination_id: The ID of the destination account.
            amount: The amount to transfer (must be between 1.00 and 5000.00).

        Returns:
            A confirmation message if transfer is successful.

        Raises:
            ValueError: If the transfer amount is invalid or accounts are inactive.
        """
        if not (1.00 <= amount <= 5000.00):
            raise ValueError("Invalid transfer amount")

        # Simulate transfer logic
        return "Transfer successful"

# Example usage:
# service = AccountService()
# service.register_account({"id": "123", "name": "John Doe", "age": 25, "type": "STANDARD", "opening": 100.0})
