# Double-Entry Financial Ledger System

A banking-grade double-entry ledger built with **MySQL 8** (Aiven cloud), **Python ETL**, and a **Flask** web interface. Every transfer creates immutable journal entries — balances are always computed live, never stored.

**Course:** CSIT 695 — Readings in Computer Science  
**Role:** Data Engineer Intern at Apex Technology Systems

---

## Features

- **Double-entry accounting** — every transfer creates balanced DEBIT/CREDIT pairs
- **Stored procedure** (`transfer_funds`) with idempotency, balance checks, and atomic transactions
- **ETL pipeline** — generates monthly bank statements with running balances
- **Web dashboard** — view balances, send money, and browse statements
- **Audit invariant** — total debits always equal total credits

---

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Flask Web   │────▶│  MySQL 8     │◀────│  ETL Pipeline    │
│  (Render)    │     │  (Aiven)     │     │  (statement_etl) │
└──────────────┘     └──────────────┘     └──────────────────┘
```

---

## Project Structure

```
ledger-project/
├── sql/
│   ├── 01_schema.sql                  # Tables: users, accounts, transactions, journal_entries
│   ├── 02_transfer_procedure.sql      # Stored procedure: transfer_funds
│   ├── 03_seed_and_test.sql           # Seed data: Alice, Bob, Carol + test transfers
│   ├── 04_views_and_reports.sql       # Views: v_account_balances, v_transaction_history, etc.
│   └── 99_account_statements_table.sql # Table: account_statements (for ETL output)
├── etl/
│   └── statement_etl.py               # Monthly statement ETL pipeline
├── scripts/
│   ├── 05_stress_test.py              # 50-transfer stress test with audit
│   └── 06_export_to_csv.py            # Export journal entries & balances to CSV
├── webapp/
│   ├── app.py                         # Flask routes (login, dashboard, statements)
│   ├── templates/
│   │   ├── base.html                  # Base template with navbar + flash messages
│   │   ├── login.html                 # User selection page
│   │   ├── dashboard.html             # Account cards + transfer form + recent activity
│   │   ├── statements.html            # Statement list + generate button
│   │   └── statement_detail.html      # Full statement breakdown
│   └── static/
│       └── style.css                  # Dark banking-themed stylesheet
├── .env.example                       # Template for environment variables
├── .gitignore                         # Ignores .env, ca.pem, __pycache__, etc.
├── requirements.txt                   # Python dependencies
├── Procfile                           # Render deployment config
└── README.md                          # This file
```

---

## Local Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/ledger-project.git
cd ledger-project
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env
```

Edit `.env` with your Aiven database credentials:

```
DB_HOST=your-host.aivencloud.com
DB_PORT=12345
DB_USER=avnadmin
DB_PASSWORD=your-password
DB_NAME=ledger_db
DB_SSL_CA=ca.pem
SECRET_KEY=generate-a-random-string
```

Download the **CA certificate** from your Aiven dashboard and save it as `ca.pem` in the project root.

### 3. Set up the database

Run the SQL files in order on your Aiven MySQL instance:

1. `sql/01_schema.sql`
2. `sql/02_transfer_procedure.sql`
3. `sql/03_seed_and_test.sql`
4. `sql/04_views_and_reports.sql`
5. `sql/99_account_statements_table.sql`

### 4. Run the web app

```bash
cd webapp
python app.py
```

Open `http://localhost:5000` in your browser.

### 5. Run the ETL (optional)

```bash
python etl/statement_etl.py                  # Current month, all users
python etl/statement_etl.py --month 2026-04  # Specific month
```

### 6. Run the stress test (optional)

```bash
python scripts/05_stress_test.py
```

---

## Deploy to Render

1. Push code to a GitHub repository
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect your GitHub repo
4. Settings:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn webapp.app:app`
5. Add **environment variables** in the Render dashboard:
   - `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
   - `DB_SSL_CA` → path to CA cert (upload `ca.pem` to your repo or use Render's secret files)
   - `SECRET_KEY` → a random string for Flask sessions
6. Deploy — Render gives you a URL like `https://ledger-app.onrender.com`

> **IMPORTANT:** Never commit `.env` or `ca.pem` to Git. Use environment variables on Render.

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `users` | Alice, Bob, Carol |
| `accounts` | Checking/Savings per user |
| `transactions` | Transfer records with idempotency keys |
| `journal_entries` | Immutable DEBIT/CREDIT entries (the heart of the system) |
| `account_statements` | ETL-generated monthly statements |

### The Golden Rule

For every successful transfer:
- 1 INSERT into `transactions`
- 2 INSERTs into `journal_entries` (one DEBIT, one CREDIT)
- All operations are **atomic** — all succeed or none do
- Total DEBITs across the system **must always equal** total CREDITs

---

## License

Student project — CSIT 695.
