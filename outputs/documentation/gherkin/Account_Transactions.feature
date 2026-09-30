Feature: Account Transactions

  Scenario: Perform debit transaction
    Given a transactionType of 'DEBIT' and an amount
    When the transaction is processed
    Then the transaction fails if the amount is <= 0
    Then the transaction fails if the account status is 'BLOCKED' or 'CLOSED'
    Then the transaction fails if the account type is 'SAVINGS' and the amount exceeds the balance
    Then the transaction fails if the account type is 'CURRENT' and the amount exceeds the balance + 10000

  Scenario: Perform credit transaction
    Given a transactionType of 'CREDIT' and an amount
    When the transaction is processed
    Then the transaction fails if the amount is <= 0
    Then the transaction fails if the account status is 'CLOSED'
