"""
statement_etl.py — Monthly Bank Statement ETL Pipeline
========================================================
Generates monthly bank statements per user from the live ledger_db.

Extract  → Pull journal entries for a given user and month
Transform→ Compute opening/closing balance, credits, debits, running balance
Load     → Write the statement into the account_statements table

Usage:
    python statement_etl.py                        # current month, all users
    python statement_etl.py --month 2026-04        # specific month, all users
    python statement_etl.py --user-id <UUID>       # current month, one user
    python statement_etl.py --month 2026-04 --user-id <UUID>

Setup:
    pip install mysql-connector-python python-dotenv
    Create a .env file with DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSL_CA
"""

import os
import json
import uuid
import argparse
from datetime import date, datetime
from decimal import Decimal

import mysql.connector
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Database connection
# ============================================================
DB_CONFIG: dict = {
    "host":            os.environ["DB_HOST"],
    "port":            int(os.environ["DB_PORT"]),
    "user":            os.environ["DB_USER"],
    "password":        os.environ["DB_PASSWORD"],
    "database":        os.environ["DB_NAME"],
    "ssl_ca":          os.environ.get("DB_SSL_CA", "ca.pem"),
    "ssl_verify_cert": True,
}


# ============================================================
# EXTRACT
# ============================================================
def extract_entries(conn, account_id: str, period_start: date, period_end: date) -> list[dict]:
    """Pull all journal entries for one account within a date range."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT
            je.entry_id,
            je.transaction_id,
            je.entry_type,
            je.amount,
            je.created_at,
            t.from_account_id,
            t.to_account_id
        FROM journal_entries je
        JOIN transactions t ON t.transaction_id = je.transaction_id
        WHERE je.account_id = %s
          AND DATE(je.created_at) >= %s
          AND DATE(je.created_at) <= %s
        ORDER BY je.created_at ASC
    """, (account_id, period_start, period_end))
    rows = cursor.fetchall()
    cursor.close()
    return rows


def extract_opening_balance(conn, account_id: str, before_date: date) -> Decimal:
    """Sum of all journal entries BEFORE the period → opening balance."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COALESCE(SUM(
            CASE entry_type
                WHEN 'CREDIT' THEN  amount
                WHEN 'DEBIT'  THEN -amount
            END
        ), 0)
        FROM journal_entries
        WHERE account_id = %s
          AND DATE(created_at) < %s
    """, (account_id, before_date))
    result = cursor.fetchone()[0]
    cursor.close()
    return Decimal(str(result))


def get_all_users(conn) -> list[dict]:
    """Return all users."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, full_name FROM users ORDER BY full_name")
    rows = cursor.fetchall()
    cursor.close()
    return rows


def get_user_accounts(conn, user_id: str) -> list[dict]:
    """Return all accounts for a given user."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT account_id, account_type, currency
        FROM accounts
        WHERE user_id = %s
        ORDER BY account_type
    """, (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    return rows


# ============================================================
# TRANSFORM
# ============================================================
def transform_statement(
    entries: list[dict],
    opening_balance: Decimal,
) -> dict:
    """
    Compute statement metrics from raw journal entries.

    Returns:
        dict with closing_balance, total_credits, total_debits,
        transaction_count, and line_items (list of dicts with running balance).
    """
    total_credits = Decimal("0.00")
    total_debits = Decimal("0.00")
    running = opening_balance
    line_items: list[dict] = []

    for entry in entries:
        amt = Decimal(str(entry["amount"]))
        if entry["entry_type"] == "CREDIT":
            total_credits += amt
            running += amt
        else:  # DEBIT
            total_debits += amt
            running -= amt

        line_items.append({
            "entry_id":       entry["entry_id"],
            "transaction_id": entry["transaction_id"],
            "entry_type":     entry["entry_type"],
            "amount":         str(amt),
            "running_balance": str(running),
            "created_at":     entry["created_at"].isoformat()
                              if isinstance(entry["created_at"], datetime) else str(entry["created_at"]),
        })

    return {
        "closing_balance":  running,
        "total_credits":    total_credits,
        "total_debits":     total_debits,
        "transaction_count": len(line_items),
        "line_items":       line_items,
    }


# ============================================================
# LOAD
# ============================================================
def load_statement(
    conn,
    user_id: str,
    account_id: str,
    period_start: date,
    period_end: date,
    opening_balance: Decimal,
    result: dict,
) -> str:
    """Insert (or update) the statement row. Returns 'INSERTED' or 'UPDATED'."""
    statement_id = uuid.uuid4().hex
    # Format as CHAR(36)
    sid = "%s-%s-%s-%s-%s" % (
        statement_id[:8], statement_id[8:12], statement_id[12:16],
        statement_id[16:20], statement_id[20:]
    )

    line_items_json = json.dumps(result["line_items"])

    cursor = conn.cursor()

    # Try INSERT; on duplicate key update
    cursor.execute("""
        INSERT INTO account_statements
            (statement_id, user_id, account_id, period_start, period_end,
             opening_balance, closing_balance, total_credits, total_debits,
             transaction_count, line_items, generated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE
            opening_balance   = VALUES(opening_balance),
            closing_balance   = VALUES(closing_balance),
            total_credits     = VALUES(total_credits),
            total_debits      = VALUES(total_debits),
            transaction_count = VALUES(transaction_count),
            line_items        = VALUES(line_items),
            generated_at      = UTC_TIMESTAMP()
    """, (
        sid, user_id, account_id,
        period_start, period_end,
        str(opening_balance), str(result["closing_balance"]),
        str(result["total_credits"]), str(result["total_debits"]),
        result["transaction_count"], line_items_json,
    ))
    action = "UPDATED" if cursor.rowcount == 2 else "INSERTED"
    conn.commit()
    cursor.close()
    return action


# ============================================================
# ORCHESTRATOR
# ============================================================
def generate_statement(
    conn,
    user_id: str,
    user_name: str,
    account: dict,
    period_start: date,
    period_end: date,
) -> None:
    """Run the full ETL for one account + one period."""
    acct_id = account["account_id"]
    acct_type = account["account_type"]

    # EXTRACT
    entries = extract_entries(conn, acct_id, period_start, period_end)
    opening = extract_opening_balance(conn, acct_id, period_start)

    # TRANSFORM
    result = transform_statement(entries, opening)

    # LOAD
    action = load_statement(conn, user_id, acct_id, period_start, period_end, opening, result)

    print("  %s  %-16s  %-10s  open=$%10s  close=$%10s  txns=%d  [%s]" % (
        user_name, acct_type, str(period_start)[:7],
        opening, result["closing_balance"],
        result["transaction_count"], action,
    ))


def main() -> None:
    """Parse args and run the ETL pipeline."""
    parser = argparse.ArgumentParser(description="Monthly statement ETL pipeline")
    parser.add_argument("--month", type=str, default=None,
                        help="Period in YYYY-MM format (default: current month)")
    parser.add_argument("--user-id", type=str, default=None,
                        help="Generate for a single user_id (default: all users)")
    args = parser.parse_args()

    # Determine period
    if args.month:
        year, month = map(int, args.month.split("-"))
    else:
        today = date.today()
        year, month = today.year, today.month

    period_start = date(year, month, 1)
    # End of month
    if month == 12:
        period_end = date(year + 1, 1, 1)
    else:
        period_end = date(year, month + 1, 1)
    from datetime import timedelta
    period_end = period_end - timedelta(days=1)

    line = "=" * 76
    print("")
    print(line)
    print("  Monthly Statement ETL — %s to %s" % (period_start, period_end))
    print("  Started: " + datetime.now().strftime("%H:%M:%S"))
    print(line)
    print("")

    conn = mysql.connector.connect(**DB_CONFIG)

    # Get users
    if args.user_id:
        users = [{"user_id": args.user_id, "full_name": "(specified)"}]
    else:
        users = get_all_users(conn)

    for user in users:
        accounts = get_user_accounts(conn, user["user_id"])
        for account in accounts:
            generate_statement(conn, user["user_id"], user["full_name"],
                               account, period_start, period_end)

    conn.close()

    print("")
    print(line)
    print("  ETL complete — %d user(s) processed" % len(users))
    print(line)
    print("")


if __name__ == "__main__":
    main()
