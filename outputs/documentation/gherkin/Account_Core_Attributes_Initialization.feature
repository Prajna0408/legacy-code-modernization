Feature: Account Core Attributes Initialization

  Scenario: Initialize account with default attributes
    Given an account with accountNumber, customerId, customerName, accountType, and balance
    When the account is initialized
    Then the status is set to 'ACTIVE'
    Then failedAttempts is set to 0
    Then kycVerified is set to false
    Then riskCategory is set to 'NORMAL'
