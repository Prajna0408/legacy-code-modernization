Feature: Account Representation

  Scenario: Generate account summary
    Given an account with accountNumber, customerId, customerName, accountType, balance, status, and riskCategory
    When the account summary is requested
    Then the summary is formatted as 'accountNumber|customerId|customerName|accountType|balance|status|riskCategory'
