Feature: Account Initialization Edge Cases

  Scenario: Initialize account with missing or invalid data
    Given A new account is created with missing or invalid accountNumber, customerId, customerName, accountType, or balance
    When The account creation process is triggered
    Then The account creation fails with an appropriate error message
