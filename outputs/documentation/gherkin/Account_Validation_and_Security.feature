Feature: Account Validation and Security

  Scenario: Authenticate account access
    Given An account with accountNumber, pin, and status
    When Authentication is attempted
    Then Authentication fails if account is null or pin is null
    Then Authentication fails if account status is 'BLOCKED'
    Then Authentication fails if pin length is not 4 or pin is '0000'
    Then Account is blocked after MAX_LOGIN_FAILURES
