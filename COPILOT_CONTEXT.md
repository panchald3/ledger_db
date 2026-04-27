# Project Context — Double-Entry Financial Ledger System

> Hand this file to GitHub Copilot (or any AI assistant) so it has full context of the project state, design decisions, and what comes next.

---

## Project Summary

A double-entry financial ledger system for tracking money movement between user accounts. Built in **MySQL 8** (hosted on **Aiven** cloud), with a **Python ETL pipeline** and a **Flask web interface**. The system follows banking-grade design: never overwrites balances, only appends immutable journal entries.

**Course:** CSIT 695 — Readings in Computer Science
**Role:** Data Engineer Intern at Apex Technology Systems

---

## Current Status — What's Already Done

### Database (live on Aiven)
- 4 tables fully migrated and operational: `users`, `accounts`, `transactions`, `journal_entries`
- 4 views: `v_account_balances`, `v_transaction_history`, `v_daily_volume`, `v_full_ledger`
- 1 stored procedure: `transfer_funds(from_id, to_id, amount, idem_key, OUT result)`
- Seed data: 3 users (Alice, Bob, Carol) + 4 accounts with starting balances
- All tables use collation `utf8mb4_0900_ai_ci` (Aiven default — converted from local)
- All `DEFINER` clauses stripped during migration (Aiven's `avnadmin` is not SUPER user)
- The procedure has been tested — real transfers work and return clean SUCCESS/ERROR/DUPLICATE messages

### Python scripts (currently point at localhost — NEED UPDATE)
- `05_stress_test.py` — fires 50 sequential transfers, runs audit at the end
- `06_export_to_csv.py` — exports today's journal entries + balances to CSV

### Documentation
- `ledger_project_documentation.docx` — full project report covering schema, procedure, tests, views, stress test, CSV export

---

## What Needs to Be Built Next

### Phase 1 — Update Python scripts for Aiven (small)
Both `05_stress_test.py` and `06_export_to_csv.py` currently hardcode `127.0.0.1`. They need:
- Aiven host, port, user, password from environment variables (NOT hardcoded for security)
- SSL cert path (`ca.pem` file from Aiven dashboard)
- `ssl_verify_cert=True` flag in connection config

### Phase 2 — Build the ETL pipeline
**File:** `statement_etl.py`

**Concept:** Generates monthly bank statements per user. Demonstrates classic Extract → Transform → Load.

**Steps:**
1. **Extract** — Pull all journal entries for a given `user_id` and `month` (e.g. `2026-04`) from the live `ledger_db`
2. **Transform** — For each of the user's accounts:
   - Calculate opening balance (sum of entries BEFORE the month)
   - Calculate closing balance (sum of all entries up to and including the month)
   - Compute total credits (money in) and total debits (money out) during the month
   - Generate a per-transaction running balance column
   - Group transactions chronologically
3. **Load** — Write the processed statement into a new table `account_statements` with columns like:
   - `statement_id`, `user_id`, `account_id`, `period_start`, `period_end`
   - `opening_balance`, `closing_balance`, `total_credits`, `total_debits`
   - `transaction_count`, `generated_at`
   - Plus a JSON column or related table for the line items with running balances

**The new table needs to be created** — write a CREATE TABLE statement first, then the ETL script.

### Phase 3 — Build the Flask web app

**Three pages:**

1. **Login page** (`/`) — A simple "select your user" page with three buttons (Alice, Bob, Carol). No real authentication. Stores selected `user_id` in Flask session.

2. **Dashboard page** (`/dashboard`) — After login. Shows:
   - The user's account cards with current balance (from `v_account_balances` view)
   - A "Send money" form: dropdown of recipient accounts, amount input, submit button
   - Form submits and calls `transfer_funds` stored procedure
   - Success/error message displayed inline

3. **Statements page** (`/statements`) — Shows:
   - List of monthly statements available for the current user (from `account_statements` table)
   - Click a statement → shows full breakdown: opening balance, transactions with running balance, totals, closing balance
   - "Generate this month's statement" button that triggers the ETL on demand

**Tech:** Flask + Jinja2 templates + plain HTML/CSS (no React, no fancy JS framework). Maybe Chart.js for one balance graph if time allows.

### Phase 4 — Deploy to Render
- Push code to a GitHub repo
- Connect repo to Render
- Add Aiven DB credentials as **environment variables** in Render dashboard (NEVER commit them)
- Add `requirements.txt` with `flask`, `mysql-connector-python`, `gunicorn`
- Add `Procfile` with `web: gunicorn app:app`
- Render gives a public URL like `https://ledger-app.onrender.com`

---

## Key Technical Notes

### Database connection pattern (mysql-connector-python + Aiven SSL)
```python
import os
import mysql.connector

DB_CONFIG = {
    "host":     os.environ["DB_HOST"],
    "port":     int(os.environ["DB_PORT"]),
    "user":     os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
    "ssl_ca":   os.environ.get("DB_SSL_CA", "ca.pem"),
    "ssl_verify_cert": True,
}

conn = mysql.connector.connect(**DB_CONFIG)
```

### Calling the stored procedure (IMPORTANT — use direct CALL, NOT callproc())
The `mysql-connector-python` `callproc()` method has version-specific quirks with OUT parameters on Aiven. Use this pattern instead:

```python
cursor = conn.cursor()
cursor.execute("SET @p_result = ''")
cursor.execute(
    "CALL transfer_funds(%s, %s, %s, %s, @p_result)",
    (from_account_id, to_account_id, amount, idempotency_key)
)
while cursor.nextset():
    pass  # consume any extra result sets
cursor.execute("SELECT @p_result")
result_message = cursor.fetchone()[0]
conn.commit()
```

### Idempotency keys
Every transfer MUST have a unique `idempotency_key`. Generate with `uuid.uuid4().hex` or a structured format like `f"WEB-{user_id}-{datetime.now().isoformat()}-{uuid.uuid4().hex[:8]}"`. The database UNIQUE constraint blocks duplicates automatically.

### Balance calculation
Account balances are NEVER stored. Always compute live:
```sql
SELECT SUM(CASE entry_type WHEN 'CREDIT' THEN amount ELSE -amount END)
FROM journal_entries WHERE account_id = ?
```
Or just `SELECT * FROM v_account_balances WHERE account_id = ?`.

---

## Database Schema Reference

### Tables

```sql
users
  user_id    CHAR(36) PK
  username   VARCHAR(50) UNIQUE
  email      VARCHAR(100) UNIQUE
  full_name  VARCHAR(100)
  created_at DATETIME

accounts
  account_id   CHAR(36) PK
  user_id      CHAR(36) FK → users
  account_type VARCHAR(20)  -- CHECKING/SAVINGS/CREDIT/INVESTMENT
  currency     CHAR(3)
  created_at   DATETIME

transactions
  transaction_id   CHAR(36) PK
  from_account_id  CHAR(36) FK → accounts
  to_account_id    CHAR(36) FK → accounts
  amount           DECIMAL(18,2)
  idempotency_key  VARCHAR(100) UNIQUE
  created_at       DATETIME

journal_entries
  entry_id       CHAR(36) PK
  transaction_id CHAR(36) FK → transactions
  account_id     CHAR(36) FK → accounts
  entry_type     ENUM('DEBIT','CREDIT')
  amount         DECIMAL(18,2)
  created_at     DATETIME
```

### The Golden Rule
For every successful transfer:
- One INSERT into `transactions`
- TWO INSERTs into `journal_entries` (one DEBIT on sender, one CREDIT on receiver)
- All three operations are atomic — they either all happen or none happen

Total DEBITs across the system MUST always equal total CREDITs. This is the audit invariant.

### Seed account IDs (for reference)
- Alice Walker — `aaaaaaaa-0001-0001-0001-000000000001`
  - Checking: `bbbbbbbb-0001-0001-0001-000000000001`
  - Savings: `bbbbbbbb-0002-0002-0002-000000000002`
- Bob Martinez — `aaaaaaaa-0002-0002-0002-000000000002`
  - Checking: `bbbbbbbb-0003-0003-0003-000000000003`
- Carol Johnson — `aaaaaaaa-0003-0003-0003-000000000003`
  - Savings: `bbbbbbbb-0004-0004-0004-000000000004`

---

## File Structure (target)

```
ledger-project/
├── sql/
│   ├── 01_schema.sql
│   ├── 02_transfer_procedure_aiven.sql
│   ├── 03_seed_and_test.sql
│   ├── 04_views_and_reports.sql
│   └── 99_account_statements_table.sql      ← NEW (Phase 2)
├── etl/
│   └── statement_etl.py                      ← NEW (Phase 2)
├── scripts/
│   ├── 05_stress_test.py                     (UPDATE for Aiven)
│   └── 06_export_to_csv.py                   (UPDATE for Aiven)
├── webapp/                                    ← NEW (Phase 3)
│   ├── app.py                                 (Flask routes)
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   └── statements.html
│   ├── static/
│   │   └── style.css
│   └── ca.pem                                 (Aiven SSL cert — gitignored!)
├── .env.example                               (template, no real secrets)
├── .gitignore                                 (must ignore .env, ca.pem)
├── requirements.txt
├── Procfile                                   (for Render)
├── README.md
└── docs/
    └── ledger_project_documentation.docx
```

---

## What I Need From You (Copilot)

Pick up at **Phase 1** and proceed sequentially. Confirm each phase works before moving to the next. Use Python type hints and short docstrings on functions. Keep code readable — this is a student project being graded, not production code.

For the Flask app, prioritize **clarity over polish**. Inline CSS is fine. Single `app.py` file is fine for now (don't split into blueprints unless it grows past ~300 lines).

When deploying to Render, document the steps in the README so the project is reproducible.

Don't hardcode any credentials anywhere. Use a `.env` file locally (loaded with `python-dotenv`) and environment variables on Render.
