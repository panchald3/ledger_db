-- ============================================================
-- FILE 3: 03_seed_and_test.sql
-- Run this THIRD — populates test data and runs all edge cases
-- ============================================================

USE ledger_db;

-- ────────────────────────────────────────────────────────────
-- SECTION A: Clear previous data (safe to re-run)
-- ────────────────────────────────────────────────────────────
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE journal_entries;
TRUNCATE TABLE transactions;
TRUNCATE TABLE accounts;
TRUNCATE TABLE users;
SET FOREIGN_KEY_CHECKS = 1;

-- ────────────────────────────────────────────────────────────
-- Insert 3 users
-- ────────────────────────────────────────────────────────────
INSERT INTO users (user_id, username, email, full_name, created_at) VALUES
  ('aaaaaaaa-0001-0001-0001-000000000001', 'alice_w', 'alice@example.com', 'Alice Walker',  UTC_TIMESTAMP()),
  ('aaaaaaaa-0002-0002-0002-000000000002', 'bob_m',   'bob@example.com',   'Bob Martinez',  UTC_TIMESTAMP()),
  ('aaaaaaaa-0003-0003-0003-000000000003', 'carol_j', 'carol@example.com', 'Carol Johnson', UTC_TIMESTAMP());

-- ────────────────────────────────────────────────────────────
-- Insert 4 accounts (no balance column — balances come from journal_entries)
-- ────────────────────────────────────────────────────────────
INSERT INTO accounts (account_id, user_id, account_type, currency, created_at) VALUES
  ('bbbbbbbb-0001-0001-0001-000000000001', 'aaaaaaaa-0001-0001-0001-000000000001', 'CHECKING', 'USD', UTC_TIMESTAMP()),
  ('bbbbbbbb-0002-0002-0002-000000000002', 'aaaaaaaa-0001-0001-0001-000000000001', 'SAVINGS',  'USD', UTC_TIMESTAMP()),
  ('bbbbbbbb-0003-0003-0003-000000000003', 'aaaaaaaa-0002-0002-0002-000000000002', 'CHECKING', 'USD', UTC_TIMESTAMP()),
  ('bbbbbbbb-0004-0004-0004-000000000004', 'aaaaaaaa-0003-0003-0003-000000000003', 'SAVINGS',  'USD', UTC_TIMESTAMP());

-- ────────────────────────────────────────────────────────────
-- Seed opening balances
-- Order: transactions FIRST, then journal_entries (FK requires this)
-- We use a special "bank" account as the from_account for opening deposits
-- ────────────────────────────────────────────────────────────

-- Step 1: insert the 4 seed transaction records
INSERT INTO transactions (transaction_id, from_account_id, to_account_id, amount, idempotency_key, created_at) VALUES
  ('00000000-0000-0000-0000-000000000001', 'bbbbbbbb-0001-0001-0001-000000000001', 'bbbbbbbb-0002-0002-0002-000000000002', 1000.00, 'SEED-ALICE-CHK', UTC_TIMESTAMP()),
  ('00000000-0000-0000-0000-000000000002', 'bbbbbbbb-0001-0001-0001-000000000001', 'bbbbbbbb-0002-0002-0002-000000000002',  500.00, 'SEED-ALICE-SAV', UTC_TIMESTAMP()),
  ('00000000-0000-0000-0000-000000000003', 'bbbbbbbb-0003-0003-0003-000000000003', 'bbbbbbbb-0004-0004-0004-000000000004',  750.00, 'SEED-BOB-CHK',   UTC_TIMESTAMP()),
  ('00000000-0000-0000-0000-000000000004', 'bbbbbbbb-0003-0003-0003-000000000003', 'bbbbbbbb-0004-0004-0004-000000000004',  200.00, 'SEED-CAROL-SAV', UTC_TIMESTAMP());

-- Step 2: now insert journal entries referencing those transaction IDs
INSERT INTO journal_entries (entry_id, transaction_id, account_id, entry_type, amount, created_at) VALUES
  -- Alice Checking opening balance: $1,000
  (UUID(), '00000000-0000-0000-0000-000000000001', 'bbbbbbbb-0001-0001-0001-000000000001', 'CREDIT', 1000.00, UTC_TIMESTAMP()),
  -- Alice Savings opening balance: $500
  (UUID(), '00000000-0000-0000-0000-000000000002', 'bbbbbbbb-0002-0002-0002-000000000002', 'CREDIT',  500.00, UTC_TIMESTAMP()),
  -- Bob Checking opening balance: $750
  (UUID(), '00000000-0000-0000-0000-000000000003', 'bbbbbbbb-0003-0003-0003-000000000003', 'CREDIT',  750.00, UTC_TIMESTAMP()),
  -- Carol Savings opening balance: $200
  (UUID(), '00000000-0000-0000-0000-000000000004', 'bbbbbbbb-0004-0004-0004-000000000004', 'CREDIT',  200.00, UTC_TIMESTAMP());

SELECT 'Seed data inserted successfully.' AS status;

-- ────────────────────────────────────────────────────────────
-- SECTION B: Starting balances (should match seeded values)
-- ────────────────────────────────────────────────────────────
SELECT
  u.full_name,
  a.account_type,
  COALESCE(SUM(
    CASE je.entry_type
      WHEN 'CREDIT' THEN  je.amount
      WHEN 'DEBIT'  THEN -je.amount
    END
  ), 0) AS balance
FROM accounts a
JOIN users u ON u.user_id = a.user_id
LEFT JOIN journal_entries je ON je.account_id = a.account_id
GROUP BY a.account_id, u.full_name, a.account_type
ORDER BY u.full_name, a.account_type;

-- ────────────────────────────────────────────────────────────
-- SECTION C: 6 TEST CASES
-- ────────────────────────────────────────────────────────────

-- TEST 1: Normal successful transfer — Alice sends $200 to Bob
SET @result = '';
CALL transfer_funds(
  'bbbbbbbb-0001-0001-0001-000000000001',
  'bbbbbbbb-0003-0003-0003-000000000003',
  200.00,
  'TEST-TRANSFER-001',
  @result
);
SELECT 'TEST 1 — Normal transfer' AS test_name, @result AS result;

-- TEST 2: Duplicate — same idempotency key as TEST 1
SET @result = '';
CALL transfer_funds(
  'bbbbbbbb-0001-0001-0001-000000000001',
  'bbbbbbbb-0003-0003-0003-000000000003',
  200.00,
  'TEST-TRANSFER-001',
  @result
);
SELECT 'TEST 2 — Duplicate key' AS test_name, @result AS result;

-- TEST 3: Overdraft — Alice only has $800, tries to send $5,000
SET @result = '';
CALL transfer_funds(
  'bbbbbbbb-0001-0001-0001-000000000001',
  'bbbbbbbb-0004-0004-0004-000000000004',
  5000.00,
  'TEST-TRANSFER-003',
  @result
);
SELECT 'TEST 3 — Overdraft' AS test_name, @result AS result;

-- TEST 4: Zero amount
SET @result = '';
CALL transfer_funds(
  'bbbbbbbb-0001-0001-0001-000000000001',
  'bbbbbbbb-0003-0003-0003-000000000003',
  0.00,
  'TEST-TRANSFER-004',
  @result
);
SELECT 'TEST 4 — Zero amount' AS test_name, @result AS result;

-- TEST 5: Invalid account ID
SET @result = '';
CALL transfer_funds(
  'bbbbbbbb-0001-0001-0001-000000000001',
  'zzzzzzzz-fake-fake-fake-zzzzzzzzzzzz',
  50.00,
  'TEST-TRANSFER-005',
  @result
);
SELECT 'TEST 5 — Invalid account' AS test_name, @result AS result;

-- TEST 6: Same account for sender and receiver
SET @result = '';
CALL transfer_funds(
  'bbbbbbbb-0001-0001-0001-000000000001',
  'bbbbbbbb-0001-0001-0001-000000000001',
  50.00,
  'TEST-TRANSFER-006',
  @result
);
SELECT 'TEST 6 — Same account' AS test_name, @result AS result;

-- ────────────────────────────────────────────────────────────
-- SECTION D: Final balances — only TEST 1 should have moved money
-- ────────────────────────────────────────────────────────────
SELECT
  u.full_name,
  a.account_type,
  COALESCE(SUM(
    CASE je.entry_type
      WHEN 'CREDIT' THEN  je.amount
      WHEN 'DEBIT'  THEN -je.amount
    END
  ), 0) AS balance
FROM accounts a
JOIN users u ON u.user_id = a.user_id
LEFT JOIN journal_entries je ON je.account_id = a.account_id
GROUP BY a.account_id, u.full_name, a.account_type
ORDER BY u.full_name, a.account_type;