"""
FILE 6: 06_export_to_csv.py
Export today's journal entries to a CSV file
=============================================
Setup:
    pip install mysql-connector-python python-dotenv

Configure:
    Create a .env file with DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSL_CA
    Then run:  python 06_export_to_csv.py

Output:
    Creates journal_YYYY-MM-DD.csv and balances_YYYY-MM-DD.csv
    in the same folder as this script.
"""

import os
import csv
from datetime import date, datetime

import mysql.connector
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================
# Database connection — reads from environment variables
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


def fetch_journal_entries(conn, export_date) -> tuple[list[str], list]:
    """Pull every journal entry for the given date."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            je.entry_id,
            je.created_at,
            u.full_name,
            a.account_type,
            je.entry_type,
            je.amount,
            je.transaction_id
        FROM journal_entries je
        JOIN accounts     a ON a.account_id     = je.account_id
        JOIN users        u ON u.user_id        = a.user_id
        JOIN transactions t ON t.transaction_id = je.transaction_id
        WHERE DATE(je.created_at) = %s
          AND t.idempotency_key NOT LIKE 'SEED-%%'
        ORDER BY je.created_at
    """, (export_date,))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    cursor.close()
    return columns, rows


def fetch_balances(conn) -> tuple[list[str], list]:
    """Pull current balance for every account."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            u.full_name,
            a.account_type,
            a.currency,
            COALESCE(SUM(
                CASE je.entry_type
                    WHEN 'CREDIT' THEN  je.amount
                    WHEN 'DEBIT'  THEN -je.amount
                END
            ), 0) AS balance
        FROM accounts a
        JOIN users u ON u.user_id = a.user_id
        LEFT JOIN journal_entries je ON je.account_id = a.account_id
        GROUP BY a.account_id, u.full_name, a.account_type, a.currency
        ORDER BY u.full_name, a.account_type
    """)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    cursor.close()
    return columns, rows


def write_csv(filepath: str, columns: list[str], rows: list) -> int:
    """Write columns + rows to a CSV file."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([str(v) if v is not None else "" for v in row])
    return len(rows)


def main() -> None:
    """Export today's journal entries and current balances to CSV."""
    today = date.today()
    line = "=" * 52
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("")
    print(line)
    print("  Ledger CSV Export (Aiven)")
    print("  Date   : " + str(today))
    print("  Started: " + datetime.now().strftime("%H:%M:%S"))
    print(line)
    print("")

    conn = mysql.connector.connect(**DB_CONFIG)

    # --- Export 1: Journal entries for today ---
    journal_file = os.path.join(script_dir, "journal_%s.csv" % today)
    cols, rows = fetch_journal_entries(conn, today)

    if rows:
        count = write_csv(journal_file, cols, rows)
        print("  Journal entries exported  : %d rows" % count)
        print("  File: " + journal_file)
    else:
        print("  No journal entries found for " + str(today))
        print("  (Run some transfers first to generate entries)")

    print("")

    # --- Export 2: Current account balances snapshot ---
    balances_file = os.path.join(script_dir, "balances_%s.csv" % today)
    cols, rows = fetch_balances(conn)
    count = write_csv(balances_file, cols, rows)
    print("  Account balances exported : %d rows" % count)
    print("  File: " + balances_file)

    conn.close()

    print("")
    print(line)
    print("  Done! Open the CSV files in Excel to view your data.")
    print(line)
    print("")


if __name__ == "__main__":
    main()
