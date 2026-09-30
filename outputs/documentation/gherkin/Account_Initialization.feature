Feature: Account Initialization

  Scenario: Initialize a new account with default attributes
    Given an account with accountNumber, customerId, customerName, accountType, and balance
    When the account is initialized
    Then the account status is set to 'ACTIVE'
    Then the failedAttempts is set to 0
    Then the kycVerified is set to false
    Then the riskCategory is set to 'NORMAL'
