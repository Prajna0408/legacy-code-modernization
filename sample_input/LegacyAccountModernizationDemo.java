/*
 * LegacyAccountModernizationDemo.java
 * Self-contained legacy-style Java program for modernization-pipeline testing.
 */
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class LegacyAccountModernizationDemo {
    private static final BigDecimal PREMIUM_THRESHOLD = new BigDecimal("10000.00");
    private static final BigDecimal STANDARD_FEE = new BigDecimal("10.00");
    private static final BigDecimal PREMIUM_FEE = new BigDecimal("5.00");
    private static final BigDecimal OVERDRAFT_FEE = new BigDecimal("35.00");
    private static final BigDecimal MIN_TRANSFER = new BigDecimal("1.00");
    private static final BigDecimal MAX_TRANSFER = new BigDecimal("5000.00");
    private final Map<String, Account> accounts = new HashMap<>();
    private final List<Transaction> transactions = new ArrayList<>();

    public static void main(String[] args) {
        LegacyAccountModernizationDemo service = new LegacyAccountModernizationDemo();
        service.seedAccounts();
        service.runDailyProcessing();
        service.printSummary();
    }

    public String registerAccount(String id, String name, int age, String type, BigDecimal opening) {
        if (id == null || id.trim().isEmpty()) return "INVALID_ACCOUNT_ID";
        if (name == null || name.trim().isEmpty()) return "INVALID_CUSTOMER_NAME";
        if (age < 18) return "CUSTOMER_MUST_BE_18_OR_OLDER";
        if (opening == null || opening.compareTo(BigDecimal.ZERO) < 0) return "INVALID_OPENING_BALANCE";
        if (accounts.containsKey(id)) return "ACCOUNT_ALREADY_EXISTS";
        if (!isValidAccountType(type)) return "INVALID_ACCOUNT_TYPE";
        accounts.put(id, new Account(id, name, age, type,
                opening.setScale(2, RoundingMode.HALF_UP), "ACTIVE"));
        return "ACCOUNT_CREATED";
    }

    private boolean isValidAccountType(String type) {
        if (type == null) return false;
        if ("STANDARD".equalsIgnoreCase(type)) return true;
        if ("PREMIUM".equalsIgnoreCase(type)) return true;
        if ("STUDENT".equalsIgnoreCase(type)) return true;
        return false;
    }

    public String activateAccount(String id) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if ("CLOSED".equals(account.status)) return "ACCOUNT_CLOSED";
        account.status = "ACTIVE";
        account.statusReason = "";
        return "ACCOUNT_ACTIVATED";
    }

    public String suspendAccount(String id, String reason) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if ("CLOSED".equals(account.status)) return "ACCOUNT_CLOSED";
        if (reason == null || reason.trim().isEmpty()) return "SUSPENSION_REASON_REQUIRED";
        account.status = "SUSPENDED";
        account.statusReason = reason;
        return "ACCOUNT_SUSPENDED";
    }

    public String closeAccount(String id) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if ("CLOSED".equals(account.status)) return "ACCOUNT_ALREADY_CLOSED";
        if (account.balance.compareTo(BigDecimal.ZERO) != 0) return "BALANCE_MUST_BE_ZERO";
        account.status = "CLOSED";
        account.classification = "CLOSED";
        return "ACCOUNT_CLOSED";
    }

    public String deposit(String id, BigDecimal amount) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if (!"ACTIVE".equals(account.status)) return "ACCOUNT_NOT_ACTIVE";
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) return "INVALID_DEPOSIT_AMOUNT";
        if (amount.compareTo(new BigDecimal("100000.00")) > 0) return "DEPOSIT_LIMIT_EXCEEDED";
        account.balance = money(account.balance.add(amount));
        recordTransaction(id, "DEPOSIT", amount, "Deposit processed");
        return "DEPOSIT_SUCCESS";
    }

    public String withdraw(String id, BigDecimal amount) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if (!"ACTIVE".equals(account.status)) return "ACCOUNT_NOT_ACTIVE";
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) return "INVALID_WITHDRAWAL_AMOUNT";
        if (amount.compareTo(account.balance) > 0) {
            account.overdraftCount++;
            account.balance = money(account.balance.subtract(OVERDRAFT_FEE));
            recordTransaction(id, "OVERDRAFT_FEE", OVERDRAFT_FEE, "Withdrawal rejected");
            return "INSUFFICIENT_FUNDS";
        }
        account.balance = money(account.balance.subtract(amount));
        recordTransaction(id, "WITHDRAWAL", amount, "Withdrawal processed");
        return "WITHDRAWAL_SUCCESS";
    }

    public String transfer(String sourceId, String destinationId, BigDecimal amount) {
        Account source = accounts.get(sourceId);
        Account destination = accounts.get(destinationId);
        if (source == null) return "SOURCE_ACCOUNT_NOT_FOUND";
        if (destination == null) return "DESTINATION_ACCOUNT_NOT_FOUND";
        if (sourceId.equals(destinationId)) return "SOURCE_AND_DESTINATION_MUST_DIFFER";
        if (!"ACTIVE".equals(source.status)) return "SOURCE_ACCOUNT_NOT_ACTIVE";
        if (!"ACTIVE".equals(destination.status)) return "DESTINATION_ACCOUNT_NOT_ACTIVE";
        if (amount == null || amount.compareTo(MIN_TRANSFER) < 0) return "TRANSFER_AMOUNT_TOO_LOW";
        if (amount.compareTo(MAX_TRANSFER) > 0) return "TRANSFER_AMOUNT_TOO_HIGH";
        if (source.balance.compareTo(amount) < 0) return "INSUFFICIENT_FUNDS";
        source.balance = money(source.balance.subtract(amount));
        destination.balance = money(destination.balance.add(amount));
        recordTransaction(sourceId, "TRANSFER_OUT", amount, "Transfer to " + destinationId);
        recordTransaction(destinationId, "TRANSFER_IN", amount, "Transfer from " + sourceId);
        return "TRANSFER_SUCCESS";
    }

    public BigDecimal calculateMonthlyFee(String id) {
        Account account = accounts.get(id);
        if (account == null || "CLOSED".equals(account.status)) return BigDecimal.ZERO;
        BigDecimal fee;
        if ("PREMIUM".equalsIgnoreCase(account.accountType)) fee = PREMIUM_FEE;
        else if ("STUDENT".equalsIgnoreCase(account.accountType)) fee = BigDecimal.ZERO;
        else fee = STANDARD_FEE;
        if (account.balance.compareTo(PREMIUM_THRESHOLD) >= 0) fee = fee.subtract(new BigDecimal("2.00"));
        if (account.age >= 60) fee = fee.subtract(new BigDecimal("1.00"));
        if (fee.compareTo(BigDecimal.ZERO) < 0) fee = BigDecimal.ZERO;
        return money(fee);
    }

    public String applyMonthlyFee(String id) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if ("CLOSED".equals(account.status)) return "ACCOUNT_CLOSED";
        BigDecimal fee = calculateMonthlyFee(id);
        if (fee.compareTo(BigDecimal.ZERO) == 0) return "NO_FEE_APPLIED";
        if (account.balance.compareTo(fee) < 0) {
            account.status = "SUSPENDED";
            account.statusReason = "Monthly fee could not be collected";
            return "ACCOUNT_SUSPENDED_FOR_FEE";
        }
        account.balance = money(account.balance.subtract(fee));
        recordTransaction(id, "MONTHLY_FEE", fee, "Monthly maintenance fee");
        return "FEE_APPLIED";
    }

    public BigDecimal calculateInterest(String id) {
        Account account = accounts.get(id);
        if (account == null || !"ACTIVE".equals(account.status)) return BigDecimal.ZERO;
        if (account.balance.compareTo(BigDecimal.ZERO) <= 0) return BigDecimal.ZERO;
        BigDecimal rate;
        if ("PREMIUM".equalsIgnoreCase(account.accountType)) rate = new BigDecimal("0.036");
        else if ("STUDENT".equalsIgnoreCase(account.accountType)) rate = new BigDecimal("0.015");
        else rate = new BigDecimal("0.024");
        if (account.age >= 60) rate = rate.add(new BigDecimal("0.005"));
        if (account.balance.compareTo(PREMIUM_THRESHOLD) >= 0) rate = rate.add(new BigDecimal("0.003"));
        BigDecimal monthly = rate.divide(new BigDecimal("12"), 10, RoundingMode.HALF_UP);
        return money(account.balance.multiply(monthly));
    }

    public String applyInterest(String id) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        BigDecimal interest = calculateInterest(id);
        if (interest.compareTo(BigDecimal.ZERO) <= 0) return "NO_INTEREST_APPLIED";
        account.balance = money(account.balance.add(interest));
        recordTransaction(id, "INTEREST", interest, "Monthly interest");
        return "INTEREST_APPLIED";
    }

    public String validateTransaction(String id, String type, BigDecimal amount) {
        if (!accounts.containsKey(id)) return "ACCOUNT_NOT_FOUND";
        if (type == null || type.trim().isEmpty()) return "TRANSACTION_TYPE_REQUIRED";
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) return "AMOUNT_MUST_BE_POSITIVE";
        if ("DEPOSIT".equalsIgnoreCase(type)) {
            if (amount.compareTo(new BigDecimal("100000.00")) > 0) return "DEPOSIT_LIMIT_EXCEEDED";
            return "VALID";
        }
        if ("WITHDRAWAL".equalsIgnoreCase(type)) {
            return amount.compareTo(accounts.get(id).balance) > 0 ? "INSUFFICIENT_FUNDS" : "VALID";
        }
        if ("TRANSFER".equalsIgnoreCase(type)) {
            if (amount.compareTo(MIN_TRANSFER) < 0) return "TRANSFER_AMOUNT_TOO_LOW";
            if (amount.compareTo(MAX_TRANSFER) > 0) return "TRANSFER_AMOUNT_TOO_HIGH";
            return "VALID";
        }
        return "UNSUPPORTED_TRANSACTION_TYPE";
    }

    public String processTransfer(String sourceId, String destinationId, BigDecimal amount) {
        String validation = validateTransaction(sourceId, "TRANSFER", amount);
        if (!"VALID".equals(validation)) return validation;
        Account source = accounts.get(sourceId);
        Account destination = accounts.get(destinationId);
        if (destination == null) return "DESTINATION_ACCOUNT_NOT_FOUND";
        if (!"ACTIVE".equals(destination.status)) return "DESTINATION_ACCOUNT_NOT_ACTIVE";
        BigDecimal fee = calculateTransferFee(sourceId, amount);
        if (source.balance.compareTo(amount.add(fee)) < 0) return "INSUFFICIENT_FUNDS_FOR_TRANSFER_AND_FEE";
        String result = transfer(sourceId, destinationId, amount);
        if ("TRANSFER_SUCCESS".equals(result) && fee.compareTo(BigDecimal.ZERO) > 0) {
            source.balance = money(source.balance.subtract(fee));
            recordTransaction(sourceId, "TRANSFER_FEE", fee, "Transfer processing fee");
        }
        return result;
    }

    public BigDecimal calculateTransferFee(String sourceId, BigDecimal amount) {
        Account source = accounts.get(sourceId);
        if (source == null || amount == null) return BigDecimal.ZERO;
        if (amount.compareTo(new BigDecimal("1000.00")) <= 0) return BigDecimal.ZERO;
        if ("PREMIUM".equalsIgnoreCase(source.accountType)) return new BigDecimal("2.00");
        if (amount.compareTo(new BigDecimal("3000.00")) > 0) return new BigDecimal("7.50");
        return new BigDecimal("5.00");
    }

    public String evaluateAccountEligibility(int age, String type, BigDecimal opening) {
        if (age < 18) return "NOT_ELIGIBLE";
        if (!isValidAccountType(type)) return "NOT_ELIGIBLE";
        if (opening == null || opening.compareTo(BigDecimal.ZERO) < 0) return "NOT_ELIGIBLE";
        if ("STUDENT".equalsIgnoreCase(type) && age > 30) return "NOT_ELIGIBLE";
        if ("PREMIUM".equalsIgnoreCase(type) && opening.compareTo(new BigDecimal("5000.00")) < 0)
            return "PREMIUM_MINIMUM_NOT_MET";
        return "ELIGIBLE";
    }

    public String classifyCustomer(int age, BigDecimal balance) {
        if (age < 18) return "MINOR";
        if (age >= 60) return balance.compareTo(PREMIUM_THRESHOLD) >= 0 ? "SENIOR_HIGH_VALUE" : "SENIOR";
        if (balance.compareTo(PREMIUM_THRESHOLD) >= 0) return "HIGH_VALUE";
        if (balance.compareTo(new BigDecimal("5000.00")) >= 0) return "STANDARD_PLUS";
        return "STANDARD";
    }

    public String determineRiskLevel(String id) {
        Account account = accounts.get(id);
        if (account == null) return "UNKNOWN";
        if ("CLOSED".equals(account.status)) return "LOW";
        if ("SUSPENDED".equals(account.status)) return "HIGH";
        if (account.overdraftCount >= 3) return "HIGH";
        if (account.overdraftCount > 0) return "MEDIUM";
        if (account.balance.compareTo(BigDecimal.ZERO) == 0) return "MEDIUM";
        return "LOW";
    }

    public String processAccount(String id) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if ("CLOSED".equals(account.status)) return "NO_PROCESSING";
        if ("SUSPENDED".equals(account.status)) return "MANUAL_REVIEW";
        String risk = determineRiskLevel(id);
        if ("HIGH".equals(risk)) {
            account.status = "SUSPENDED";
            account.statusReason = "High risk account";
            return "ACCOUNT_SUSPENDED";
        }
        if ("MEDIUM".equals(risk)) return "ACCOUNT_FLAGGED";
        return "ACCOUNT_OK";
    }

    public String updateAccountType(String id, String newType) {
        Account account = accounts.get(id);
        if (account == null) return "ACCOUNT_NOT_FOUND";
        if ("CLOSED".equals(account.status)) return "ACCOUNT_CLOSED";
        if (!isValidAccountType(newType)) return "INVALID_ACCOUNT_TYPE";
        if ("STUDENT".equalsIgnoreCase(newType) && account.age > 30) return "STUDENT_ACCOUNT_NOT_ALLOWED";
        return "ACCOUNT_TYPE_CHANGE_APPROVED";
    }

    public void runDailyProcessing() {
        for (Account account : accounts.values()) {
            if ("CLOSED".equals(account.status)) continue;
            if ("SUSPENDED".equals(account.status)) continue;
            applyInterest(account.accountId);
        }
        for (Account account : accounts.values()) {
            if ("CLOSED".equals(account.status)) continue;
            if ("SUSPENDED".equals(account.status)) continue;
            applyMonthlyFee(account.accountId);
        }
        refreshAccountClassification();
    }

    private void refreshAccountClassification() {
        for (Account account : accounts.values()) {
            if ("CLOSED".equals(account.status)) account.classification = "CLOSED";
            else if ("SUSPENDED".equals(account.status)) account.classification = "REVIEW_REQUIRED";
            else if (account.balance.compareTo(PREMIUM_THRESHOLD) >= 0) account.classification = "HIGH_VALUE";
            else if (account.balance.compareTo(new BigDecimal("5000.00")) >= 0) account.classification = "STANDARD_PLUS";
            else if (account.balance.compareTo(BigDecimal.ZERO) == 0) account.classification = "ZERO_BALANCE";
            else account.classification = "STANDARD";
        }
    }

    public Account getAccount(String id) { return accounts.get(id); }

    public List<Account> getActiveAccounts() {
        List<Account> result = new ArrayList<>();
        for (Account account : accounts.values()) if ("ACTIVE".equals(account.status)) result.add(account);
        return result;
    }

    public List<Account> getAccountsByClassification(String classification) {
        List<Account> result = new ArrayList<>();
        for (Account account : accounts.values())
            if (classification != null && classification.equalsIgnoreCase(account.classification)) result.add(account);
        return result;
    }

    public BigDecimal getTotalBalances() {
        BigDecimal total = BigDecimal.ZERO;
        for (Account account : accounts.values())
            if (!"CLOSED".equals(account.status)) total = total.add(account.balance);
        return money(total);
    }

    public int countActiveAccounts() {
        int count = 0;
        for (Account account : accounts.values()) if ("ACTIVE".equals(account.status)) count++;
        return count;
    }

    public int countSuspendedAccounts() {
        int count = 0;
        for (Account account : accounts.values()) if ("SUSPENDED".equals(account.status)) count++;
        return count;
    }

    public int countClosedAccounts() {
        int count = 0;
        for (Account account : accounts.values()) if ("CLOSED".equals(account.status)) count++;
        return count;
    }

    public List<Transaction> getTransactionsForAccount(String id) {
        List<Transaction> result = new ArrayList<>();
        for (Transaction transaction : transactions)
            if (id.equals(transaction.accountId)) result.add(transaction);
        return result;
    }

    public List<Transaction> getTransactions() {
        return Collections.unmodifiableList(transactions);
    }

    private void recordTransaction(String id, String type, BigDecimal amount, String description) {
        transactions.add(new Transaction(transactions.size() + 1, id, type, money(amount), description, LocalDate.now()));
    }

    private BigDecimal money(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    private void seedAccounts() {
        registerAccount("ACC1001", "Asha Rao", 35, "STANDARD", new BigDecimal("7500.00"));
        registerAccount("ACC1002", "Ravi Kumar", 64, "PREMIUM", new BigDecimal("15000.00"));
        registerAccount("ACC1003", "Meera Shah", 22, "STUDENT", new BigDecimal("1200.00"));
        registerAccount("ACC1004", "Vikram Das", 45, "STANDARD", new BigDecimal("3000.00"));
        transfer("ACC1001", "ACC1004", new BigDecimal("500.00"));
        deposit("ACC1003", new BigDecimal("250.00"));
        withdraw("ACC1004", new BigDecimal("100.00"));
    }

    public void printSummary() {
        System.out.println("ACCOUNT SUMMARY");
        System.out.println("----------------");
        for (Account account : accounts.values()) {
            System.out.println(account.accountId + " | " + account.customerName + " | "
                    + account.status + " | " + account.classification + " | balance=" + account.balance);
        }
        System.out.println("Active accounts: " + countActiveAccounts());
        System.out.println("Suspended accounts: " + countSuspendedAccounts());
        System.out.println("Closed accounts: " + countClosedAccounts());
        System.out.println("Total balances: " + getTotalBalances());
        System.out.println("Transactions: " + transactions.size());
    }

    public static class Account {
        private final String accountId;
        private final String customerName;
        private final int age;
        private final String accountType;
        private BigDecimal balance;
        private String status;
        private String statusReason;
        private String classification;
        private int overdraftCount;

        public Account(String id, String name, int age, String type, BigDecimal balance, String status) {
            this.accountId = id;
            this.customerName = name;
            this.age = age;
            this.accountType = type;
            this.balance = balance;
            this.status = status;
            this.statusReason = "";
            this.classification = "STANDARD";
        }

        public String getAccountId() { return accountId; }
        public String getCustomerName() { return customerName; }
        public int getAge() { return age; }
        public String getAccountType() { return accountType; }
        public BigDecimal getBalance() { return balance; }
        public String getStatus() { return status; }
        public String getStatusReason() { return statusReason; }
        public String getClassification() { return classification; }
        public int getOverdraftCount() { return overdraftCount; }
    }

    public static class Transaction {
        private final int transactionId;
        private final String accountId;
        private final String type;
        private final BigDecimal amount;
        private final String description;
        private final LocalDate transactionDate;

        public Transaction(int id, String accountId, String type, BigDecimal amount,
                           String description, LocalDate date) {
            this.transactionId = id;
            this.accountId = accountId;
            this.type = type;
            this.amount = amount;
            this.description = description;
            this.transactionDate = date;
        }

        public int getTransactionId() { return transactionId; }
        public String getAccountId() { return accountId; }
        public String getType() { return type; }
        public BigDecimal getAmount() { return amount; }
        public String getDescription() { return description; }
        public LocalDate getTransactionDate() { return transactionDate; }
    }
}
