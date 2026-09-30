Feature: Account State Edge Cases

  Scenario: Update account state with invalid data
    Given An account with invalid status, kycVerified, or riskCategory
    When The account state update process is triggered
    Then The account state update fails with an appropriate error message
