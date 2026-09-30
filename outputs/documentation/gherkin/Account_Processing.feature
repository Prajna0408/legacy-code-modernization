Feature: Account Processing

  Scenario: Verify KYC details
    Given An account with accountNumber, documentType, and documentNumber
    When KYC verification is performed
    Then The verification fails if documentNumber is null or less than 6 characters
    Then The verification fails if documentType is not 'PAN', 'PASSPORT', or 'AADHAAR'
