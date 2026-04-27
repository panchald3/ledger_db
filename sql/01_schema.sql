-- ============================================================
-- FILE 1: 01_schema.sql
-- Double-Entry Financial Ledger System
-- Run this FIRST in MySQL Workbench
-- ============================================================

-- Create and select the database
CREATE DATABASE IF NOT EXISTS ledger_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ledger_db;

-- ────────────────────────────────────────────────
-- TABLE 1: USERS
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  user_id    CHAR(36)     NOT NULL DEFAULT (UUID()),
  username   VARCHAR(50)  NOT NULL UNIQUE,
  email      VARCHAR(100) NOT NULL UNIQUE,
  full_name  VARCHAR(100) NOT NULL,
  created_at DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),

  PRIMARY KEY (user_id)
);

-- ────────────────────────────────────────────────
-- TABLE 2: ACCOUNTS
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
  account_id   CHAR(36)      NOT NULL DEFAULT (UUID()),
  user_id      CHAR(36)      NOT NULL,
  account_type VARCHAR(20)   NOT NULL,
  currency     CHAR(3)       NOT NULL DEFAULT 'USD',
  created_at   DATETIME      NOT NULL DEFAULT (UTC_TIMESTAMP()),

  PRIMARY KEY (account_id),
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT,

  CONSTRAINT chk_account_type CHECK (account_type IN ('CHECKING', 'SAVINGS', 'CREDIT', 'INVESTMENT'))
);

-- ────────────────────────────────────────────────
-- TABLE 3: TRANSACTIONS
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
  transaction_id    CHAR(36)       NOT NULL DEFAULT (UUID()),
  from_account_id   CHAR(36)       NOT NULL,
  to_account_id     CHAR(36)       NOT NULL,
  amount            DECIMAL(18, 2) NOT NULL,
  idempotency_key   VARCHAR(100)   NOT NULL UNIQUE,  -- prevents duplicate transfers
  created_at        DATETIME       NOT NULL DEFAULT (UTC_TIMESTAMP()),

  PRIMARY KEY (transaction_id),
  FOREIGN KEY (from_account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
  FOREIGN KEY (to_account_id)   REFERENCES accounts(account_id) ON DELETE RESTRICT,

  CONSTRAINT chk_txn_amount     CHECK (amount > 0),
  CONSTRAINT chk_txn_diff_accts CHECK (from_account_id <> to_account_id)
);

-- ────────────────────────────────────────────────
-- TABLE 4: JOURNAL_ENTRIES  (the heart of the system)
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS journal_entries (
  entry_id       CHAR(36)       NOT NULL DEFAULT (UUID()),
  transaction_id CHAR(36)       NOT NULL,
  account_id     CHAR(36)       NOT NULL,
  entry_type     ENUM('DEBIT','CREDIT') NOT NULL,   -- only DEBIT or CREDIT allowed
  amount         DECIMAL(18, 2) NOT NULL,
  created_at     DATETIME       NOT NULL DEFAULT (UTC_TIMESTAMP()),

  PRIMARY KEY (entry_id),
  FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id) ON DELETE RESTRICT,
  FOREIGN KEY (account_id)     REFERENCES accounts(account_id)         ON DELETE RESTRICT,

  CONSTRAINT chk_je_amount CHECK (amount > 0)
);

-- ────────────────────────────────────────────────
-- INDEXES for query performance
-- ────────────────────────────────────────────────
CREATE INDEX idx_accounts_user      ON accounts       (user_id);
CREATE INDEX idx_txn_from           ON transactions   (from_account_id);
CREATE INDEX idx_txn_to             ON transactions   (to_account_id);
CREATE INDEX idx_txn_idem           ON transactions   (idempotency_key);
CREATE INDEX idx_je_transaction     ON journal_entries(transaction_id);
CREATE INDEX idx_je_account         ON journal_entries(account_id);
CREATE INDEX idx_je_account_type    ON journal_entries(account_id, entry_type);

SELECT 'Schema created successfully.' AS status;