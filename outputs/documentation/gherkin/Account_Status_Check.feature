Feature: Account Status Check

  Scenario: Unnamed scenario
    Given The account status is 'BLOCKED'
    When The account status is checked
    Then The output is true

  Scenario: Unnamed scenario
    Given The account status is not 'BLOCKED'
    When The account status is checked
    Then The output is false
