"""Quick script to create the account_statements table on Aiven."""
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":            os.environ["DB_HOST"],
    "port":            int(os.environ["DB_PORT"]),
    "user":            os.environ["DB_USER"],
    "password":        os.environ["DB_PASSWORD"],
    "database":        os.environ["DB_NAME"],
    "ssl_ca":          os.environ.get("DB_SSL_CA", "ca.pem"),
    "ssl_verify_cert": True,
}

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

print("Connected to Aiven MySQL!")

# Create account_statements table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS account_statements (
      statement_id     CHAR(36)        NOT NULL DEFAULT (UUID()),
      user_id          CHAR(36)        NOT NULL,
      account_id       CHAR(36)        NOT NULL,
      period_start     DATE            NOT NULL,
      period_end       DATE            NOT NULL,
      opening_balance  DECIMAL(18, 2)  NOT NULL,
      closing_balance  DECIMAL(18, 2)  NOT NULL,
      total_credits    DECIMAL(18, 2)  NOT NULL DEFAULT 0.00,
      total_debits     DECIMAL(18, 2)  NOT NULL DEFAULT 0.00,
      transaction_count INT            NOT NULL DEFAULT 0,
      line_items       JSON            NULL,
      generated_at     DATETIME        NOT NULL DEFAULT (UTC_TIMESTAMP()),
      PRIMARY KEY (statement_id),
      FOREIGN KEY (user_id)    REFERENCES users(user_id)       ON DELETE RESTRICT,
      FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
      UNIQUE KEY uq_account_period (account_id, period_start, period_end)
    )
""")
print("Table account_statements created (or already exists).")

# Create indexes (ignore errors if they already exist)
try:
    cursor.execute("CREATE INDEX idx_stmt_user   ON account_statements (user_id)")
    print("Index idx_stmt_user created.")
except mysql.connector.Error as e:
    print(f"Index idx_stmt_user: {e.msg}")

try:
    cursor.execute("CREATE INDEX idx_stmt_period ON account_statements (period_start, period_end)")
    print("Index idx_stmt_period created.")
except mysql.connector.Error as e:
    print(f"Index idx_stmt_period: {e.msg}")

conn.commit()

# Quick verification — list all tables
cursor.execute("SHOW TABLES")
tables = cursor.fetchall()
print("\nTables in ledger_db:")
for t in tables:
    print(f"  - {t[0]}")

cursor.close()
conn.close()
print("\nDone!")
