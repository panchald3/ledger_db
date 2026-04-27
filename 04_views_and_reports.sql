-- ============================================================
-- FILE 4: 04_views_and_reports.sql
-- Analytical SQL views and audit queries
-- Run this FOURTH (after seeding data)
-- ============================================================

USE ledger_db;

-- ────────────────────────────────────────────────────────────
-- VIEW 1: Account Balances
-- Real-time balance for every account (computed from journal)
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_account_balances AS
SELECT
  a.account_id,
  u.full_name,
  u.email,
  a.account_type,
  a.currency,
  COALESCE(SUM(
    CASE je.entry_type
      WHEN 'CREDIT' THEN  je.amount
      WHEN 'DEBIT'  THEN -je.amount
    END
  ), 0) AS balance
FROM accounts a
JOIN  users u          ON u.user_id    = a.user_id
LEFT JOIN journal_entries je ON je.account_id = a.account_id
GROUP BY a.account_id, u.full_name, u.email, a.account_type, a.currency;

-- ────────────────────────────────────────────────────────────
-- VIEW 2: Transaction History (human-readable)
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_transaction_history AS
SELECT
  t.transaction_id,
  t.created_at                    AS transfer_date,
  sender.full_name                AS from_user,
  fa.account_type                 AS from_account_type,
  receiver.full_name              AS to_user,
  ta.account_type                 AS to_account_type,
  t.amount,
  t.idempotency_key
FROM transactions t
JOIN accounts fa    ON fa.account_id = t.from_account_id
JOIN accounts ta    ON ta.account_id = t.to_account_id
JOIN users    sender   ON sender.user_id   = fa.user_id
JOIN users    receiver ON receiver.user_id = ta.user_id
ORDER BY t.created_at DESC;

-- ────────────────────────────────────────────────────────────
-- VIEW 3: Daily Transfer Volume
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_daily_volume AS
SELECT
  DATE(created_at)     AS transfer_day,
  COUNT(*)             AS num_transactions,
  SUM(amount)          AS total_amount,
  MIN(amount)          AS min_transfer,
  MAX(amount)          AS max_transfer,
  AVG(amount)          AS avg_transfer
FROM transactions
WHERE idempotency_key NOT LIKE 'SEED-%'   -- exclude seed data
GROUP BY DATE(created_at)
ORDER BY transfer_day DESC;

-- ────────────────────────────────────────────────────────────
-- VIEW 4: Full Ledger (every journal entry, readable)
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_full_ledger AS
SELECT
  je.entry_id,
  je.created_at,
  u.full_name,
  a.account_type,
  je.entry_type,
  je.amount,
  t.transaction_id
FROM journal_entries je
JOIN accounts     a ON a.account_id     = je.account_id
JOIN users        u ON u.user_id        = a.user_id
JOIN transactions t ON t.transaction_id = je.transaction_id
WHERE t.idempotency_key NOT LIKE 'SEED-%'
ORDER BY je.created_at DESC;

SELECT '✔ Views created.' AS status;

-- ────────────────────────────────────────────────────────────
-- AUDIT QUERY — The Golden Rule of Double-Entry:
-- Total DEBITs must equal Total CREDITs (excluding seed data)
-- If the result is NOT zero, there is a bug in the system.
-- ────────────────────────────────────────────────────────────
SELECT
  SUM(CASE je.entry_type WHEN 'DEBIT'  THEN je.amount ELSE 0 END) AS total_debits,
  SUM(CASE je.entry_type WHEN 'CREDIT' THEN je.amount ELSE 0 END) AS total_credits,
  SUM(CASE je.entry_type WHEN 'DEBIT'  THEN je.amount ELSE 0 END) -
  SUM(CASE je.entry_type WHEN 'CREDIT' THEN je.amount ELSE 0 END) AS difference,
  CASE
    WHEN SUM(CASE je.entry_type WHEN 'DEBIT'  THEN je.amount ELSE 0 END) =
         SUM(CASE je.entry_type WHEN 'CREDIT' THEN je.amount ELSE 0 END)
    THEN 'BALANCED -- ledger is correct'
    ELSE 'UNBALANCED -- investigate immediately'
  END AS audit_result
FROM journal_entries je
JOIN transactions t ON t.transaction_id = je.transaction_id
WHERE t.idempotency_key NOT LIKE 'SEED-%';

-- ── Quick views to run any time ──────────────────────────────
-- SELECT * FROM v_account_balances;
-- SELECT * FROM v_transaction_history;
-- SELECT * FROM v_daily_volume;
-- SELECT * FROM v_full_ledger;