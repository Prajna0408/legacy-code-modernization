Feature: Account State Management

  Scenario: Update account state attributes
    Given an account with status, kycVerified, riskCategory, and failedAttemptsAction
    When the account state is updated
    Then failedAttempts can be increased or reset
    Then status, KYC verification, and risk category can be updated
