Feature: Account Operations

  Scenario: Perform debit operation with valid conditions
    Given an account with accountNumber, accountType, balance, and status 'ACTIVE'
    Given kycVerified is true
    When a debit operation is performed with a positive amount
    Then the operation is successful
    Then the balance is updated

  Scenario: Fail debit operation due to invalid conditions
    Given an account with accountNumber, accountType, balance, and status 'BLOCKED' or 'CLOSED'
    When a debit operation is performed
    Then the operation fails

  Scenario: Perform credit operation with valid conditions
    Given an account with accountNumber, accountType, balance, and status 'ACTIVE'
    Given kycVerified is true
    When a credit operation is performed with a positive amount
    Then the operation is successful
    Then the balance is updated

  Scenario: Fail credit operation due to invalid conditions
    Given an account with accountNumber and status 'CLOSED'
    When a credit operation is performed
    Then the operation fails
