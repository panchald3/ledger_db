-- ============================================================
-- FILE 2: 02_transfer_procedure.sql
-- Run this SECOND — after 01_schema.sql
-- ============================================================

USE ledger_db;

DROP PROCEDURE IF EXISTS transfer_funds;

DELIMITER $$

CREATE PROCEDURE transfer_funds (
  IN  p_from_account_id  CHAR(36),
  IN  p_to_account_id    CHAR(36),
  IN  p_amount           DECIMAL(18,2),
  IN  p_idempotency_key  VARCHAR(100),
  OUT p_result           VARCHAR(200)
)
-- The label wraps the ENTIRE BEGIN...END body.
-- Every LEAVE statement references this label.
transfer_funds_label: BEGIN

  -- ── Local variables ───────────────────────────────────────
  DECLARE v_from_balance  DECIMAL(18,2) DEFAULT 0;
  DECLARE v_to_exists     INT           DEFAULT 0;
  DECLARE v_txn_id        CHAR(36);
  DECLARE v_dup_count     INT           DEFAULT 0;

  -- ── Emergency exit: undo everything on any unexpected error
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    SET p_result = 'ERROR: Unexpected database error. Transaction rolled back.';
  END;

  -- ────────────────────────────────────────────────────────
  -- STEP 1 — Fast input validation (no DB queries yet)
  -- ────────────────────────────────────────────────────────
  IF p_amount IS NULL OR p_amount <= 0 THEN
    SET p_result = 'ERROR: Amount must be a positive number.';
    LEAVE transfer_funds_label;
  END IF;

  IF p_from_account_id = p_to_account_id THEN
    SET p_result = 'ERROR: Sender and receiver accounts cannot be the same.';
    LEAVE transfer_funds_label;
  END IF;

  -- ────────────────────────────────────────────────────────
  -- STEP 2 — Idempotency check (duplicate request guard)
  -- ────────────────────────────────────────────────────────
  SELECT COUNT(*) INTO v_dup_count
    FROM transactions
   WHERE idempotency_key = p_idempotency_key;

  IF v_dup_count > 0 THEN
    SET p_result = 'DUPLICATE: This transfer was already processed (idempotency key reused).';
    LEAVE transfer_funds_label;
  END IF;

  -- ────────────────────────────────────────────────────────
  -- STEP 3 — Validate both accounts exist
  -- ────────────────────────────────────────────────────────
  SELECT COUNT(*) INTO v_to_exists
    FROM accounts
   WHERE account_id IN (p_from_account_id, p_to_account_id);

  IF v_to_exists < 2 THEN
    SET p_result = 'ERROR: One or both account IDs do not exist.';
    LEAVE transfer_funds_label;
  END IF;

  -- ────────────────────────────────────────────────────────
  -- STEP 4 — Start transaction & lock rows
  --          Always lock smaller UUID first to prevent deadlocks
  -- ────────────────────────────────────────────────────────
  START TRANSACTION;

  IF p_from_account_id < p_to_account_id THEN

    SELECT COALESCE(SUM(
             CASE entry_type
               WHEN 'CREDIT' THEN  amount
               WHEN 'DEBIT'  THEN -amount
             END), 0)
      INTO v_from_balance
      FROM journal_entries
     WHERE account_id = p_from_account_id
       FOR UPDATE;

    SELECT COUNT(*) INTO v_to_exists
      FROM journal_entries
     WHERE account_id = p_to_account_id
       FOR UPDATE;

  ELSE

    SELECT COUNT(*) INTO v_to_exists
      FROM journal_entries
     WHERE account_id = p_to_account_id
       FOR UPDATE;

    SELECT COALESCE(SUM(
             CASE entry_type
               WHEN 'CREDIT' THEN  amount
               WHEN 'DEBIT'  THEN -amount
             END), 0)
      INTO v_from_balance
      FROM journal_entries
     WHERE account_id = p_from_account_id
       FOR UPDATE;

  END IF;

  -- ────────────────────────────────────────────────────────
  -- STEP 5 — Overdraft prevention
  -- ────────────────────────────────────────────────────────
  IF v_from_balance < p_amount THEN
    ROLLBACK;
    SET p_result = CONCAT('ERROR: Insufficient funds. Available balance: $',
                          FORMAT(v_from_balance, 2));
    LEAVE transfer_funds_label;
  END IF;

  -- ────────────────────────────────────────────────────────
  -- STEP 6 — Insert the transaction record (the receipt)
  -- ────────────────────────────────────────────────────────
  SET v_txn_id = UUID();

  INSERT INTO transactions
    (transaction_id, from_account_id, to_account_id, amount, idempotency_key, created_at)
  VALUES
    (v_txn_id, p_from_account_id, p_to_account_id, p_amount, p_idempotency_key, UTC_TIMESTAMP());

  -- ────────────────────────────────────────────────────────
  -- STEP 7 — Insert the two journal entries (double-entry)
  --          DEBIT  = money leaves the sender
  --          CREDIT = money arrives at the receiver
  -- ────────────────────────────────────────────────────────
  INSERT INTO journal_entries
    (entry_id, transaction_id, account_id, entry_type, amount, created_at)
  VALUES
    (UUID(), v_txn_id, p_from_account_id, 'DEBIT',  p_amount, UTC_TIMESTAMP()),
    (UUID(), v_txn_id, p_to_account_id,   'CREDIT', p_amount, UTC_TIMESTAMP());

  -- ────────────────────────────────────────────────────────
  -- STEP 8 — Commit everything atomically
  -- ────────────────────────────────────────────────────────
  COMMIT;

  SET p_result = CONCAT('SUCCESS: Transferred $', FORMAT(p_amount, 2),
                        ' | Transaction ID: ', v_txn_id);

END$$

DELIMITER ;

SELECT 'Stored procedure transfer_funds created.' AS status;