"""
Lead Management System - Flask Backend
Simple, clean, beginner-friendly lead tracker for 2 users.
"""

import os
import csv
import io
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, g, make_response, flash
)

app = Flask(__name__)

# Secret key for sessions — change this in production!
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# ─── Database path (relative, works locally and on Render) ───────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")

# ─── Hardcoded users (no database needed for auth) ──────────────────────────
USERS = {
    "user1": "password123",
    "user2": "password123",
}

# ─── Valid dropdown choices ───────────────────────────────────────────────────
CATEGORIES = ["Gym", "Salon", "Car Detailing", "Agency", "Other"]
STATUSES   = ["New", "Contacted", "Closed"]


# ═══════════════════════════════════════════════════════════════
# DATABASE SETUP
# ═══════════════════════════════════════════════════════════════

def get_db():
    """Open a database connection, reuse it within the same request."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row  # rows behave like dicts
    return g.db


@app.teardown_appcontext
def close_db(error):
    """Close the database connection after each request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the leads table if it doesn't exist."""
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT    NOT NULL,
            phone         TEXT    NOT NULL UNIQUE,
            email         TEXT    UNIQUE,
            website       TEXT,
            category      TEXT    NOT NULL DEFAULT 'Other',
            notes         TEXT,
            status        TEXT    NOT NULL DEFAULT 'New',
            assigned_to   TEXT    NOT NULL,
            date_added    TEXT    NOT NULL
        )
    """)
    db.commit()
    db.close()


# ═══════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════

def login_required(f):
    """Decorator — redirect to login if user is not in session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def normalize_phone(raw: str) -> str:
    """
    Strip spaces/dashes and ensure +91 prefix.
    Examples:
        '98765 43210'  → '+919876543210'
        '+919876543210' → '+919876543210'
        '9876543210'   → '+919876543210'
    """
    cleaned = raw.strip().replace(" ", "").replace("-", "")
    if not cleaned.startswith("+"):
        # If user typed just the 10-digit number, prepend +91
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = "+" + cleaned
        else:
            cleaned = "+91" + cleaned
    return cleaned


# ═══════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route("/", methods=["GET", "POST"])
def login():
    """Login page. Redirect to dashboard if already logged in."""
    if "user" in session:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if USERS.get(username) == password:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    """Clear session and redirect to login."""
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    """Main dashboard — shows all leads with search/filter/sort."""
    db = get_db()

    # Read query params for filtering
    search   = request.args.get("search", "").strip()
    category = request.args.get("category", "")
    status   = request.args.get("status", "")
    assigned = request.args.get("assigned", "")

    # Build SQL dynamically based on active filters
    query  = "SELECT * FROM leads WHERE 1=1"
    params = []

    if search:
        query += " AND (business_name LIKE ? OR phone LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if category:
        query += " AND category = ?"
        params.append(category)
    if status:
        query += " AND status = ?"
        params.append(status)
    if assigned:
        query += " AND assigned_to = ?"
        params.append(assigned)

    query += " ORDER BY id DESC"  # newest first

    leads = db.execute(query, params).fetchall()

    return render_template(
        "dashboard.html",
        leads=leads,
        categories=CATEGORIES,
        statuses=STATUSES,
        users=list(USERS.keys()),
        current_user=session["user"],
        # Pass back active filters so the UI can reflect them
        search=search, active_category=category,
        active_status=status, active_assigned=assigned,
    )


# ═══════════════════════════════════════════════════════════════
# ADD LEAD
# ═══════════════════════════════════════════════════════════════

@app.route("/add", methods=["POST"])
@login_required
def add_lead():
    """Receive the add-lead form, validate, and insert into DB."""
    db = get_db()

    business_name = request.form.get("business_name", "").strip()
    raw_phone     = request.form.get("phone", "").strip()
    email         = request.form.get("email", "").strip() or None
    website       = request.form.get("website", "").strip() or None
    category      = request.form.get("category", "Other")
    notes         = request.form.get("notes", "").strip() or None
    assigned_to   = request.form.get("assigned_to", "user1")

    # Basic validation
    if not business_name or not raw_phone:
        flash("Business name and phone are required.", "error")
        return redirect(url_for("dashboard"))

    phone = normalize_phone(raw_phone)

    # Duplicate check — phone
    existing_phone = db.execute(
        "SELECT id FROM leads WHERE phone = ?", (phone,)
    ).fetchone()
    if existing_phone:
        flash(f"A lead with phone {phone} already exists.", "error")
        return redirect(url_for("dashboard"))

    # Duplicate check — email (only if provided)
    if email:
        existing_email = db.execute(
            "SELECT id FROM leads WHERE email = ?", (email,)
        ).fetchone()
        if existing_email:
            flash(f"A lead with email {email} already exists.", "error")
            return redirect(url_for("dashboard"))

    date_added = datetime.now().strftime("%Y-%m-%d %H:%M")

    db.execute(
        """INSERT INTO leads
           (business_name, phone, email, website, category, notes, status, assigned_to, date_added)
           VALUES (?, ?, ?, ?, ?, ?, 'New', ?, ?)""",
        (business_name, phone, email, website, category, notes, assigned_to, date_added)
    )
    db.commit()
    flash("Lead added successfully!", "success")
    return redirect(url_for("dashboard"))


# ═══════════════════════════════════════════════════════════════
# EDIT LEAD
# ═══════════════════════════════════════════════════════════════

@app.route("/edit/<int:lead_id>", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id):
    """Edit status, notes, and assigned_to for an existing lead."""
    db = get_db()
    lead = db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()

    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        status      = request.form.get("status", lead["status"])
        notes       = request.form.get("notes", "").strip() or None
        assigned_to = request.form.get("assigned_to", lead["assigned_to"])

        db.execute(
            "UPDATE leads SET status=?, notes=?, assigned_to=? WHERE id=?",
            (status, notes, assigned_to, lead_id)
        )
        db.commit()
        flash("Lead updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "edit.html",
        lead=lead,
        statuses=STATUSES,
        users=list(USERS.keys()),
        current_user=session["user"],
    )


# ═══════════════════════════════════════════════════════════════
# DELETE LEAD
# ═══════════════════════════════════════════════════════════════

@app.route("/delete/<int:lead_id>", methods=["POST"])
@login_required
def delete_lead(lead_id):
    """Delete a lead by ID."""
    db = get_db()
    db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    db.commit()
    flash("Lead deleted.", "success")
    return redirect(url_for("dashboard"))


# ═══════════════════════════════════════════════════════════════
# CSV EXPORT
# ═══════════════════════════════════════════════════════════════

@app.route("/export/emails")
@login_required
def export_emails():
    """Export a single-column CSV of all non-empty email addresses."""
    db  = get_db()
    rows = db.execute(
        "SELECT email FROM leads WHERE email IS NOT NULL AND email != '' ORDER BY id DESC"
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email"])
    for row in rows:
        writer.writerow([row["email"]])

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=emails.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


@app.route("/export/leads")
@login_required
def export_leads():
    """Export all leads (optionally filtered by category) as CSV."""
    db       = get_db()
    category = request.args.get("category", "")

    if category:
        rows = db.execute(
            "SELECT * FROM leads WHERE category = ? ORDER BY id DESC", (category,)
        ).fetchall()
        filename = f"leads_{category.lower().replace(' ', '_')}.csv"
    else:
        rows = db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        filename = "leads_all.csv"

    output = io.StringIO()
    writer = csv.writer(output)
    # Header row
    writer.writerow([
        "ID", "Business Name", "Phone", "Email", "Website",
        "Category", "Notes", "Status", "Assigned To", "Date Added"
    ])
    for row in rows:
        writer.writerow([
            row["id"], row["business_name"], row["phone"], row["email"] or "",
            row["website"] or "", row["category"], row["notes"] or "",
            row["status"], row["assigned_to"], row["date_added"]
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-Type"] = "text/csv"
    return response


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()  # create table if it doesn't exist
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
else:
    # Called by gunicorn — still need to init the DB
    init_db()
