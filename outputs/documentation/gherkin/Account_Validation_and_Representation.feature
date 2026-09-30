Feature: Account Validation and Representation

  Scenario: Validate account for transactions
    Given an account with status and kycVerified
    When the account is validated for transactions
    Then transactions are allowed only if the account status is 'ACTIVE' and KYC is verified

  Scenario: Generate account representation
    Given an account with core attributes
    When the account representation is generated
    Then the account representation is a concatenated string of core attributes
