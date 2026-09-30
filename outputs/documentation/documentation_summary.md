# Legacy System Technical Documentation

## 1. Purpose and Scope

This document provides the human-readable engineering view of the legacy application derived from the source-code decomposition performed upstream in the modernization pipeline.

It is intended for developers, technical leads, architects, testers, and maintainers who need to understand the existing system before implementing the target solution.

Gherkin and OpenAPI are intentionally kept as separate artifacts; this document focuses on technical understanding and traceability.

## 2. System Overview

## Account Lifecycle Management

### Overview
The Account Lifecycle Management module provides APIs to manage the lifecycle of customer accounts, including registration, activation, suspension, closure, and financial transactions such as deposits, withdrawals, and transfers.

### Business Rules
1. **Account Registration**:
   - Account ID, name, and type must be valid and non-empty.
   - Customer must be at least 18 years old to register an account.
   - Opening balance must be non-negative.
   - Account type must be one of `STANDARD`, `PREMIUM`, or `STUDENT`.
   - If the account type is invalid, return an `INVALID_ACCOUNT_TYPE` error.
   - If the customer is under 18, return an `UNDERAGE_CUSTOMER` error.
   - If the opening balance is negative, return an `INVALID_OPENING_BALANCE` error.

2. **Account Activation**:
   - The account must exist and have a valid ID.

3. **Account Suspension**:
   - The account must exist and have a valid ID.
   - A reason must be provided for suspension.

4. **Account Closure**:
   - The account must exist and have a valid ID.

5. **Deposits**:
   - The account must be active.
   - The deposit amount must be positive and not exceed 100,000.00.

6. **Withdrawals**:
   - The account must be active.
   - The withdrawal amount must not exceed the account balance unless overdraft is allowed.

7. **Transfers**:
   - Both source and destination accounts must be active.
   - The transfer amount must be between 1.00 and 5000.00.
   - Source and destination accounts must differ.

### API Endpoints
Refer to the OpenAPI specification for detailed API definitions, including request and response formats, validation rules, and error handling.

## 3. Logical Module Inventory

| Module | Source File(s) | Responsibility |
|---|---|---|
| AccountLifecycleManagement | `LegacyAccountModernizationDemo.java` | Account Management |
| ValidationAndControlFlow | `LegacyAccountModernizationDemo.java` | Validation and Control Flow |
| AccountStatusValidation | `LegacyAccountModernizationDemo.java` | Account Validation and Status Checks |
| FinancialOperations | `LegacyAccountModernizationDemo.java` | Account Financial Operations |
| InterestApplication | `LegacyAccountModernizationDemo.java` | Unspecified |
| TransferAndFeeManagement | `LegacyAccountModernizationDemo.java` | Transfer and Fee Management |
| AccountEligibilityAndClassification | `LegacyAccountModernizationDemo.java` | Account Eligibility and Classification |
| RiskAssessmentAndProcessing | `LegacyAccountModernizationDemo.java` | Risk Assessment and Account Processing |
| AccountTypeManagement | `LegacyAccountModernizationDemo.java` | Account Type Management |
| DailyAccountProcessing | `LegacyAccountModernizationDemo.java` | Daily Account Processing |
| TransactionManagement | `LegacyAccountModernizationDemo.java` | Transaction Management |
| UtilityAndInitialization | `LegacyAccountModernizationDemo.java` | Utility and Initialization |
| TransactionDetails | `LegacyAccountModernizationDemo.java` | TransactionDetails |

## 4. Detailed Module Documentation

### 4.1 AccountLifecycleManagement

**Responsibility / Domain Context**

Account Management

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Registeraccount:** {
  "id": "String",
  "name": "String",
  "age": "int",
  "type": "String",
  "opening": "BigDecimal"
}
- **Activateaccount:** {
  "id": "String"
}
- **Suspendaccount:** {
  "id": "String",
  "reason": "String"
}
- **Closeaccount:** {
  "id": "String"
}
- **Deposit:** {
  "id": "String",
  "amount": "BigDecimal"
}
- **Withdraw:** {
  "id": "String",
  "amount": "BigDecimal"
}
- **Transfer:** {
  "sourceId": "String",
  "destinationId": "String",
  "amount": "BigDecimal"
}

### Output Contract

- **Registeraccount:** String
- **Activateaccount:** String
- **Suspendaccount:** String
- **Closeaccount:** String
- **Deposit:** String
- **Withdraw:** String
- **Transfer:** String

### Business Rules

- Account ID, name, and type must be valid and non-empty.
- Customer must be at least 18 years old to register an account.
- Opening balance must be non-negative.
- Account must not already exist for the given ID.
- Account type must be one of STANDARD, PREMIUM, or STUDENT.
- Account must be ACTIVE to perform deposit, withdrawal, or transfer.
- Deposit amount must be positive and not exceed 100,000.00.
- Withdrawal amount must not exceed account balance unless overdraft is allowed.
- Transfer amount must be between 1.00 and 5000.00 and source and destination accounts must differ.

### 4.2 ValidationAndControlFlow

**Responsibility / Domain Context**

Validation and Control Flow

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Validateaccountregistration:** {
  "id": "String",
  "name": "String",
  "age": "int",
  "type": "String",
  "opening": "BigDecimal"
}
- **Validatetransaction:** {
  "id": "String",
  "type": "String",
  "amount": "BigDecimal"
}

### Output Contract

- **Validateaccountregistration:** String
- **Validatetransaction:** String

### Business Rules

- Account ID and name must not be null or empty.
- Customer age must be at least 18.
- Opening balance must be non-negative.
- Account type must be valid.
- Transaction type must be specified and valid.
- Transaction amount must be positive.
- Deposit amount must not exceed 100,000.00.
- Transfer amount must be within allowed limits.

### 4.3 AccountStatusValidation

**Responsibility / Domain Context**

Account Validation and Status Checks

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Validateaccountstatus:** {
  "id": "String"
}
- **Validatetransactionamount:** {
  "sourceId": "String",
  "destinationId": "String",
  "amount": "BigDecimal"
}

### Output Contract

- **Validateaccountstatus:** String
- **Validatetransactionamount:** String

### Business Rules

- Account must be ACTIVE to perform operations.
- Destination account must be ACTIVE for transfers.
- Transfer amount must be within the minimum and maximum limits.
- Source account must have sufficient funds for the transfer.

### 4.4 FinancialOperations

**Responsibility / Domain Context**

Account Financial Operations

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Calculatemonthlyfee:** {
  "id": "String"
}
- **Applymonthlyfee:** {
  "id": "String"
}
- **Calculateinterest:** {
  "id": "String"
}
- **Processtransfer:** {
  "sourceId": "String",
  "destinationId": "String",
  "amount": "BigDecimal"
}

### Output Contract

- **Calculatemonthlyfee:** BigDecimal
- **Applymonthlyfee:** String
- **Calculateinterest:** BigDecimal
- **Processtransfer:** String

### Business Rules

- Monthly fee depends on account type, balance, and customer age.
- Interest rate depends on account type, balance, and customer age.
- Transfer fees are calculated based on amount and account type.
- Account balance must be sufficient to cover transfer amount and fees.

### 4.5 InterestApplication

**Responsibility / Domain Context**

Unspecified

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Applyinterest:** {
  "id": "String"
}

### Output Contract

- **Applyinterest:** String

### Business Rules

- Interest is applied only to ACTIVE accounts with a positive balance.
- Interest rate is determined by account type, balance, and customer age.

### 4.6 TransferAndFeeManagement

**Responsibility / Domain Context**

Transfer and Fee Management

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Calculatetransferfee:** {
  "sourceId": "String",
  "amount": "BigDecimal"
}

### Output Contract

- **Calculatetransferfee:** BigDecimal

### Business Rules

- Transfer fees depend on the amount and account type.
- No fee is applied for transfers below 1000.00.
- Premium accounts have a lower transfer fee.

### 4.7 AccountEligibilityAndClassification

**Responsibility / Domain Context**

Account Eligibility and Classification

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Evaluateaccounteligibility:** {
  "age": "int",
  "type": "String",
  "opening": "BigDecimal"
}
- **Classifycustomer:** {
  "age": "int",
  "balance": "BigDecimal"
}

### Output Contract

- **Evaluateaccounteligibility:** String
- **Classifycustomer:** String

### Business Rules

- Customers under 18 are not eligible for accounts.
- Student accounts are not allowed for customers over 30.
- Premium accounts require a minimum opening balance of 5000.00.
- Customer classification depends on age and balance thresholds.

### 4.8 RiskAssessmentAndProcessing

**Responsibility / Domain Context**

Risk Assessment and Account Processing

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Determinerisklevel:** {
  "id": "String"
}
- **Processaccount:** {
  "id": "String"
}

### Output Contract

- **Determinerisklevel:** String
- **Processaccount:** String

### Business Rules

- Risk level is determined based on account status, overdraft count, and balance.
- High-risk accounts are suspended automatically.
- Medium-risk accounts are flagged for review.

### 4.9 AccountTypeManagement

**Responsibility / Domain Context**

Account Type Management

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Id:** String
- **Newtype:** String

### Output Contract

- **Status:** String

### Business Rules

- If the account is not found, return 'ACCOUNT_NOT_FOUND'.
- If the account status is 'CLOSED', return 'ACCOUNT_CLOSED'.
- If the new account type is invalid, return 'INVALID_ACCOUNT_TYPE'.
- If the new account type is 'STUDENT' and the account holder's age is greater than 30, return 'STUDENT_ACCOUNT_NOT_ALLOWED'.
- If all validations pass, return 'ACCOUNT_TYPE_CHANGE_APPROVED'.

### 4.10 DailyAccountProcessing

**Responsibility / Domain Context**

Daily Account Processing

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Accounts:** [
  {
    "accountId": "String",
    "status": "String"
  }
]

### Output Contract

- **Processedaccounts:** [
  {
    "accountId": "String",
    "interestApplied": "Boolean",
    "feeApplied": "Boolean"
  }
]

### Business Rules

- Skip processing for accounts with status 'CLOSED'.
- Skip processing for accounts with status 'SUSPENDED'.
- Apply interest to eligible accounts.
- Apply monthly fees to eligible accounts.
- Refresh account classifications after processing.

### 4.11 TransactionManagement

**Responsibility / Domain Context**

Transaction Management

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Accountid:** String
- **Transactiondetails:** {
  "id": "String",
  "type": "String",
  "amount": "BigDecimal",
  "description": "String"
}

### Output Contract

- **Transactions:** [
  {
    "transactionId": "int",
    "accountId": "String",
    "type": "String",
    "amount": "BigDecimal",
    "description": "String",
    "transactionDate": "LocalDate"
  }
]

### Business Rules

- Retrieve all transactions for a specific account ID.
- Return an unmodifiable list of all transactions.
- Record a new transaction with the provided details.

### 4.12 UtilityAndInitialization

**Responsibility / Domain Context**

Utility and Initialization

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Value:** BigDecimal
- **Accounts:** [
  {
    "accountId": "String",
    "customerName": "String",
    "age": "int",
    "type": "String",
    "balance": "BigDecimal"
  }
]

### Output Contract

- **Formattedvalue:** BigDecimal
- **Summary:** String

### Business Rules

- Format monetary values to two decimal places using HALF_UP rounding mode.
- Seed accounts with predefined data for initialization.
- Print a summary of account information including account ID, customer name, status, classification, and balance.

### 4.13 TransactionDetails

**Responsibility / Domain Context**

TransactionDetails

**Legacy Source Files**

- `LegacyAccountModernizationDemo.java`

### Input Contract

- **Transaction:** {
  "transactionId": "int",
  "accountId": "String",
  "type": "String",
  "amount": "BigDecimal",
  "description": "String",
  "transactionDate": "LocalDate"
}

### Output Contract

- **Transactionid:** int
- **Accountid:** String
- **Type:** String
- **Amount:** BigDecimal
- **Description:** String
- **Transactiondate:** LocalDate

### Business Rules

- Provide getter methods for transaction properties including transaction ID, account ID, type, amount, description, and transaction date.

## 5. End-to-End Processing Flow

The legacy modernization flow represented by this stage is:

1. Legacy source files are parsed/analyzed upstream.
2. The Splitting Agent decomposes the source into logical modules and source slices.
3. The Documentation Agent consumes module contracts, business rules, source references, and evaluation feedback when a retry is required.
4. Gherkin scenarios are produced as behavior-oriented verification specifications.
5. An OpenAPI 3.0 interface is produced from supported module contracts and validated.
6. This document provides the human-readable engineering explanation.

## 6. Interface Summary

- **API Title:** Account Lifecycle Management API
- **API Version:** 1.0.0

| Method | Path | Operation |
|---|---|---|
| POST | /registerAccount | Register a new account |
| POST | /activateAccount | Activate an account |
| POST | /suspendAccount | Suspend an account |
| POST | /closeAccount | Close an account |
| POST | /deposit | Deposit into an account |
| POST | /withdraw | Withdraw from an account |
| POST | /transfer | Transfer between accounts |

**OpenAPI validation status:** True

The complete OpenAPI specification remains in the separate `openapi.yaml` artifact.

## 7. Related Verification Artifacts

Detailed Gherkin scenario text is deliberately not embedded here. The generated feature files remain the dedicated behavior-specification artifacts.

- `Account_Lifecycle_Management.feature`

## 8. Modernization Notes

Use the source traceability, module contracts, and business rules as evidence when implementing the target system. Behavior that is not represented in the decomposed input should be verified against the original legacy source before it is carried forward.

This document is descriptive technical documentation. Gherkin remains the behavior specification and OpenAPI remains the service-interface specification.
