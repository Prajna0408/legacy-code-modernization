Feature: Risk Category Management

  Scenario: Unnamed scenario
    Given The transaction amount is greater than or equal to HIGH_RISK_THRESHOLD
    When The risk category is evaluated
    Then The risk category is set to 'HIGH'

  Scenario: Unnamed scenario
    Given The account balance is greater than or equal to PREMIUM_THRESHOLD
    When The risk category is evaluated
    Then The risk category is set to 'PREMIUM'
