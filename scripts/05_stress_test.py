"""
FILE 5: 05_stress_test.py
Transfer stress test — Double-Entry Financial Ledger
======================================================
Setup:
    pip install mysql-connector-python python-dotenv

Configure:
    Create a .env file with DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSL_CA
    Then run:  python 05_stress_test.py
"""

import os
import uuid
import random
import time
from datetime import datetime

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

TOTAL_TRANSFERS: int = 50  # how many transfers to fire

ACCOUNTS: list[str] = [
    "bbbbbbbb-0001-0001-0001-000000000001",
    "bbbbbbbb-0002-0002-0002-000000000002",
    "bbbbbbbb-0003-0003-0003-000000000003",
    "bbbbbbbb-0004-0004-0004-000000000004",
]


def run_one_transfer(conn, transfer_num: int) -> dict:
    """Run a single transfer using an existing connection."""
    from_acct, to_acct = random.sample(ACCOUNTS, 2)
    amount = round(random.uniform(1.00, 80.00), 2)
    idem_key = "STRESS-%03d-%s" % (transfer_num, uuid.uuid4().hex[:8])

    try:
        cursor = conn.cursor()
        cursor.execute("SET @p_result = ''")
        cursor.execute(
            "CALL transfer_funds(%s, %s, %s, %s, @p_result)",
            (from_acct, to_acct, amount, idem_key),
        )
        # Consume any extra result sets
        while cursor.nextset():
            pass
        cursor.execute("SELECT @p_result")
        row = cursor.fetchone()
        result = row[0] if (row and row[0]) else "UNKNOWN"
        conn.commit()
        cursor.close()
        return {"num": transfer_num, "amount": amount, "result": result}
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"num": transfer_num, "amount": amount, "result": "EXCEPTION: " + str(exc)}


def run_audit(conn) -> tuple[float, float]:
    """Check that total debits == total credits."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
          SUM(CASE je.entry_type WHEN 'DEBIT'  THEN je.amount ELSE 0 END),
          SUM(CASE je.entry_type WHEN 'CREDIT' THEN je.amount ELSE 0 END)
        FROM journal_entries je
        JOIN transactions t ON t.transaction_id = je.transaction_id
        WHERE t.idempotency_key NOT LIKE 'SEED-%%'
    """)
    row = cursor.fetchone()
    cursor.close()
    return float(row[0] or 0), float(row[1] or 0)


def main() -> None:
    """Run the stress test: fire transfers, tally results, audit the ledger."""
    line = "=" * 56

    print("")
    print(line)
    print("  Double-Entry Ledger — Stress Test (Aiven)")
    print("  %d transfers" % TOTAL_TRANSFERS)
    print("  Started: " + datetime.now().strftime("%H:%M:%S"))
    print(line)
    print("")

    results: list[dict] = []

    conn = mysql.connector.connect(**DB_CONFIG)

    for i in range(1, TOTAL_TRANSFERS + 1):
        r = run_one_transfer(conn, i)
        results.append(r)
        tag = "[OK]" if r["result"].startswith("SUCCESS") else "[--]"
        print("  %s #%02d  $%6.2f   %s" % (tag, r["num"], r["amount"], r["result"][:48]))
        time.sleep(0.02)

    # Tally
    success      = sum(1 for r in results if r["result"].startswith("SUCCESS"))
    insufficient = sum(1 for r in results if "Insufficient" in r["result"])
    duplicates   = sum(1 for r in results if r["result"].startswith("DUPLICATE"))
    exceptions   = sum(1 for r in results if r["result"].startswith("EXCEPTION"))

    print("")
    print(line)
    print("  Summary")
    print(line)
    print("  Successful transfers      : %d" % success)
    print("  Blocked — low balance     : %d" % insufficient)
    print("  Blocked — duplicate key   : %d" % duplicates)
    print("  Exceptions                : %d" % exceptions)
    print("  Total                     : %d" % len(results))

    # Audit
    print("")
    print(line)
    print("  Audit — debits must equal credits")
    print(line)
    debits, credits_ = run_audit(conn)
    diff = abs(debits - credits_)
    print("  Total DEBITs  : $%.2f" % debits)
    print("  Total CREDITs : $%.2f" % credits_)
    print("  Difference    : $%.2f" % diff)
    print("")
    if diff < 0.001:
        print("  RESULT: LEDGER IS BALANCED — no data corruption.")
    else:
        print("  RESULT: LEDGER IS UNBALANCED — investigate!")

    conn.close()
    print("")
    print("  Finished: " + datetime.now().strftime("%H:%M:%S"))
    print(line)
    print("")


if __name__ == "__main__":
    main()
