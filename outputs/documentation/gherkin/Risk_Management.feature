Feature: Risk Management

  Scenario: Update risk category based on transaction
    Given An account with balance and riskCategory
    Given A transaction amount
    When The risk category is updated
    Then High-risk transactions are flagged based on thresholds
    Then Premium accounts are identified by balance thresholds
    Then Transactions exceeding review thresholds are categorized accordingly
    Then Normal risk category is assigned if no other criteria are met
