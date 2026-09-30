Feature: Account Closure

  Scenario: Unnamed scenario
    Given an account with accountNumber '12345' has status 'ACTIVE' and balance 1000.0
    When a closure request is made
    Then the account is not closed
    Then the status remains 'ACTIVE'

  Scenario: Unnamed scenario
    Given an account with accountNumber '12345' has status 'ACTIVE' and balance 0.0
    When a closure request is made
    Then the account is closed
    Then the status is updated to 'CLOSED'
