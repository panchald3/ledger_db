"""
app.py — Flask Web Application for Double-Entry Financial Ledger
=================================================================
Three pages:
  /            — Login (select user)
  /dashboard   — Account cards + send money form
  /statements  — Monthly statements list + detail + generate button

Setup:
    pip install flask mysql-connector-python python-dotenv
    Create a .env with DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSL_CA, SECRET_KEY
    python app.py
"""

import os
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from dotenv import load_dotenv

# Load .env from project root (parent of webapp/)
_dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_dotenv_path)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ============================================================
# Database helpers
# ============================================================
# Resolve SSL cert path relative to project root (parent of webapp/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ssl_ca_env = os.environ.get("DB_SSL_CA", "ca.pem")
_SSL_CA_PATH = _ssl_ca_env if os.path.isabs(_ssl_ca_env) else os.path.join(_PROJECT_ROOT, _ssl_ca_env)

DB_CONFIG: dict = {
    "host":            os.environ["DB_HOST"],
    "port":            int(os.environ["DB_PORT"]),
    "user":            os.environ["DB_USER"],
    "password":        os.environ["DB_PASSWORD"],
    "database":        os.environ["DB_NAME"],
    "ssl_ca":          _SSL_CA_PATH,
    "ssl_verify_cert": True,
}


def get_db():
    """Create and return a fresh database connection."""
    return mysql.connector.connect(**DB_CONFIG)


# ============================================================
# Custom Jinja filter
# ============================================================
@app.template_filter("currency")
def currency_filter(value) -> str:
    """Format a number as USD currency string."""
    try:
        val = float(value)
        return "${:,.2f}".format(val)
    except (ValueError, TypeError):
        return "$0.00"


# ============================================================
# ROUTE: Login
# ============================================================
@app.route("/", methods=["GET"])
def login():
    """Show a simple user-selection login page."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, username, full_name FROM users ORDER BY full_name")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("login.html", users=users)


@app.route("/login", methods=["POST"])
def do_login():
    """Set the selected user in session and redirect to dashboard."""
    user_id = request.form.get("user_id")
    if not user_id:
        flash("Please select a user.", "error")
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, username, full_name FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user:
        flash("User not found.", "error")
        return redirect(url_for("login"))

    session["user_id"] = user["user_id"]
    session["full_name"] = user["full_name"]
    session["username"] = user["username"]
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    """Clear session and return to login."""
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# ROUTE: Dashboard
# ============================================================
@app.route("/dashboard")
def dashboard():
    """Show account cards and transfer form."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Get user's accounts with balances
    cursor.execute("""
        SELECT
            a.account_id,
            a.account_type,
            a.currency,
            COALESCE(SUM(
                CASE je.entry_type
                    WHEN 'CREDIT' THEN  je.amount
                    WHEN 'DEBIT'  THEN -je.amount
                END
            ), 0) AS balance
        FROM accounts a
        LEFT JOIN journal_entries je ON je.account_id = a.account_id
        WHERE a.user_id = %s
        GROUP BY a.account_id, a.account_type, a.currency
        ORDER BY a.account_type
    """, (user_id,))
    accounts = cursor.fetchall()

    # Get all OTHER accounts (for transfer dropdown)
    cursor.execute("""
        SELECT
            a.account_id,
            a.account_type,
            u.full_name
        FROM accounts a
        JOIN users u ON u.user_id = a.user_id
        WHERE a.user_id <> %s
        ORDER BY u.full_name, a.account_type
    """, (user_id,))
    other_accounts = cursor.fetchall()

    # Recent transactions for this user (last 10)
    cursor.execute("""
        SELECT
            t.created_at,
            t.amount,
            je.entry_type,
            a_other.account_type AS other_account_type,
            u_other.full_name AS other_user,
            a_mine.account_type AS my_account_type
        FROM journal_entries je
        JOIN transactions t ON t.transaction_id = je.transaction_id
        JOIN accounts a_mine ON a_mine.account_id = je.account_id
        LEFT JOIN journal_entries je2 ON je2.transaction_id = t.transaction_id
            AND je2.account_id <> je.account_id
        LEFT JOIN accounts a_other ON a_other.account_id = je2.account_id
        LEFT JOIN users u_other ON u_other.user_id = a_other.user_id
        WHERE a_mine.user_id = %s
          AND t.idempotency_key NOT LIKE 'SEED-%%'
        ORDER BY t.created_at DESC
        LIMIT 10
    """, (user_id,))
    recent_txns = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("dashboard.html",
                           accounts=accounts,
                           other_accounts=other_accounts,
                           recent_txns=recent_txns)


@app.route("/transfer", methods=["POST"])
def transfer():
    """Process a money transfer."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    from_account_id = request.form.get("from_account_id")
    to_account_id = request.form.get("to_account_id")
    amount_str = request.form.get("amount", "0")

    # Validation
    if not from_account_id or not to_account_id:
        flash("Please select both source and destination accounts.", "error")
        return redirect(url_for("dashboard"))

    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError
    except (ValueError, ArithmeticError):
        flash("Please enter a valid amount greater than zero.", "error")
        return redirect(url_for("dashboard"))

    # Generate idempotency key
    idem_key = "WEB-%s-%s-%s" % (
        session["user_id"][:8],
        datetime.now().strftime("%Y%m%d%H%M%S"),
        uuid.uuid4().hex[:8],
    )

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SET @p_result = ''")
        cursor.execute(
            "CALL transfer_funds(%s, %s, %s, %s, @p_result)",
            (from_account_id, to_account_id, str(amount), idem_key),
        )
        # Consume extra result sets
        while cursor.nextset():
            pass
        cursor.execute("SELECT @p_result")
        row = cursor.fetchone()
        result_message = row[0] if (row and row[0]) else "UNKNOWN"
        conn.commit()
        cursor.close()

        if result_message.startswith("SUCCESS"):
            flash("Transfer of $%.2f completed successfully!" % amount, "success")
        else:
            flash("Transfer failed: %s" % result_message, "error")
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        flash("Transfer error: %s" % str(exc), "error")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: Statements
# ============================================================
@app.route("/statements")
def statements():
    """Show available monthly statements for the current user."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Get all statements for this user
    cursor.execute("""
        SELECT
            s.statement_id,
            s.account_id,
            a.account_type,
            s.period_start,
            s.period_end,
            s.opening_balance,
            s.closing_balance,
            s.total_credits,
            s.total_debits,
            s.transaction_count,
            s.generated_at
        FROM account_statements s
        JOIN accounts a ON a.account_id = s.account_id
        WHERE s.user_id = %s
        ORDER BY s.period_start DESC, a.account_type
    """, (user_id,))
    stmt_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("statements.html", statements=stmt_list)


@app.route("/statements/<statement_id>")
def statement_detail(statement_id: str):
    """Show full breakdown of a single statement."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            s.*,
            a.account_type,
            a.currency
        FROM account_statements s
        JOIN accounts a ON a.account_id = s.account_id
        WHERE s.statement_id = %s AND s.user_id = %s
    """, (statement_id, session["user_id"]))
    stmt = cursor.fetchone()

    cursor.close()
    conn.close()

    if not stmt:
        flash("Statement not found.", "error")
        return redirect(url_for("statements"))

    # Parse the JSON line items
    line_items = []
    if stmt.get("line_items"):
        raw = stmt["line_items"]
        if isinstance(raw, str):
            line_items = json.loads(raw)
        else:
            line_items = raw

    return render_template("statement_detail.html", stmt=stmt, line_items=line_items)


@app.route("/statements/generate", methods=["POST"])
def generate_statement():
    """Generate (or regenerate) this month's statement on demand."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today = date.today()
    period_start = date(today.year, today.month, 1)
    if today.month == 12:
        period_end = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(today.year, today.month + 1, 1) - timedelta(days=1)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Get user's accounts
    cursor.execute("SELECT account_id, account_type FROM accounts WHERE user_id = %s", (user_id,))
    accounts = cursor.fetchall()

    generated = 0
    for account in accounts:
        acct_id = account["account_id"]

        # EXTRACT — opening balance (sum of all entries before this month)
        cursor.execute("""
            SELECT COALESCE(SUM(
                CASE entry_type WHEN 'CREDIT' THEN amount WHEN 'DEBIT' THEN -amount END
            ), 0) AS bal
            FROM journal_entries
            WHERE account_id = %s AND DATE(created_at) < %s
        """, (acct_id, period_start))
        opening = Decimal(str(cursor.fetchone()["bal"]))

        # EXTRACT — entries in period
        cursor.execute("""
            SELECT
                je.entry_id, je.transaction_id, je.entry_type,
                je.amount, je.created_at
            FROM journal_entries je
            WHERE je.account_id = %s
              AND DATE(je.created_at) >= %s
              AND DATE(je.created_at) <= %s
            ORDER BY je.created_at ASC
        """, (acct_id, period_start, period_end))
        entries = cursor.fetchall()

        # TRANSFORM
        running = opening
        total_credits = Decimal("0")
        total_debits = Decimal("0")
        line_items = []

        for entry in entries:
            amt = Decimal(str(entry["amount"]))
            if entry["entry_type"] == "CREDIT":
                total_credits += amt
                running += amt
            else:
                total_debits += amt
                running -= amt
            line_items.append({
                "entry_id": entry["entry_id"],
                "transaction_id": entry["transaction_id"],
                "entry_type": entry["entry_type"],
                "amount": str(amt),
                "running_balance": str(running),
                "created_at": entry["created_at"].isoformat()
                              if isinstance(entry["created_at"], datetime) else str(entry["created_at"]),
            })

        closing = running

        # LOAD — upsert
        sid = str(uuid.uuid4())
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
            sid, user_id, acct_id,
            period_start, period_end,
            str(opening), str(closing),
            str(total_credits), str(total_debits),
            len(line_items), json.dumps(line_items),
        ))
        generated += 1

    conn.commit()
    cursor.close()
    conn.close()

    flash("Generated %d statement(s) for %s." % (generated, period_start.strftime("%B %Y")), "success")
    return redirect(url_for("statements"))


# ============================================================
# Run
# ============================================================
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
