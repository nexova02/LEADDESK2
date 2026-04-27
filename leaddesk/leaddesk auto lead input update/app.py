"""
NEXOVA LeadDesk — Lead Management + AI Cold Email Campaign System
Supports: Gemini, OpenAI, Groq, Mistral, or any OpenAI-compatible API
"""

import os, csv, io, json, sqlite3, smtplib, time, urllib.request, urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, g, make_response, flash)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "leads.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

USERS      = {"user1": "password123", "user2": "password123"}
CATEGORIES = ["Gym", "Salon", "Car Detailing", "Agency", "Other"]
STATUSES   = ["New", "Contacted", "Closed"]

# ── AI Provider configs ────────────────────────────────────────────────────────
# Each provider needs: url_template, auth_header, request_body_builder, response_parser
AI_PROVIDERS = {
    "gemini": {
        "label": "Google Gemini (Free)",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        "key_placeholder": "AIzaSy...",
        "key_hint": "Get free key at aistudio.google.com → API Keys",
    },
    "openai": {
        "label": "OpenAI (GPT-4o)",
        "url": "https://api.openai.com/v1/chat/completions",
        "key_placeholder": "sk-...",
        "key_hint": "Get key at platform.openai.com → API Keys",
    },
    "groq": {
        "label": "Groq (Free — Very Fast)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_placeholder": "gsk_...",
        "key_hint": "Get free key at console.groq.com → API Keys",
    },
    "mistral": {
        "label": "Mistral AI (Free tier)",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key_placeholder": "...",
        "key_hint": "Get free key at console.mistral.ai → API Keys",
    },
    "custom": {
        "label": "Custom / Other (OpenAI-compatible)",
        "url": "",
        "key_placeholder": "your-api-key",
        "key_hint": "Paste any OpenAI-compatible base URL below (e.g. https://api.together.xyz/v1/chat/completions)",
    },
}


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
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
    db.execute("""
        CREATE TABLE IF NOT EXISTS campaign_logs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id  INTEGER NOT NULL,
            email    TEXT    NOT NULL,
            subject  TEXT    NOT NULL,
            body     TEXT    NOT NULL,
            status   TEXT    NOT NULL DEFAULT 'sent',
            sent_at  TEXT    NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    db.commit()
    db.close()


# ── Auth ───────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def normalize_phone(raw):
    cleaned = raw.strip().replace(" ", "").replace("-", "")
    if not cleaned.startswith("+"):
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = "+" + cleaned
        else:
            cleaned = "+91" + cleaned
    return cleaned


# ── Auth Routes ────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
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
    session.clear()
    return redirect(url_for("login"))


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    search   = request.args.get("search", "").strip()
    category = request.args.get("category", "")
    status   = request.args.get("status", "")
    assigned = request.args.get("assigned", "")

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
    query += " ORDER BY id DESC"
    leads = db.execute(query, params).fetchall()

    return render_template(
        "dashboard.html", leads=leads, categories=CATEGORIES,
        statuses=STATUSES, users=list(USERS.keys()),
        current_user=session["user"], search=search,
        active_category=category, active_status=status, active_assigned=assigned,
    )


# ── Add Lead ───────────────────────────────────────────────────────────────────

@app.route("/add", methods=["POST"])
@login_required
def add_lead():
    db = get_db()
    business_name = request.form.get("business_name", "").strip()
    raw_phone     = request.form.get("phone", "").strip()
    email         = request.form.get("email", "").strip() or None
    website       = request.form.get("website", "").strip() or None
    category      = request.form.get("category", "Other")
    notes         = request.form.get("notes", "").strip() or None
    assigned_to   = request.form.get("assigned_to", "user1")

    if not business_name or not raw_phone:
        flash("Business name and phone are required.", "error")
        return redirect(url_for("dashboard"))

    phone = normalize_phone(raw_phone)

    if db.execute("SELECT id FROM leads WHERE phone = ?", (phone,)).fetchone():
        flash(f"Phone {phone} already exists.", "error")
        return redirect(url_for("dashboard"))
    if email and db.execute("SELECT id FROM leads WHERE email = ?", (email,)).fetchone():
        flash(f"Email {email} already exists.", "error")
        return redirect(url_for("dashboard"))

    db.execute(
        "INSERT INTO leads (business_name,phone,email,website,category,notes,status,assigned_to,date_added) VALUES (?,?,?,?,?,?,'New',?,?)",
        (business_name, phone, email, website, category, notes, assigned_to,
         datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    db.commit()
    flash("Lead added!", "success")
    return redirect(url_for("dashboard"))


# ── CSV Import ─────────────────────────────────────────────────────────────────

@app.route("/import", methods=["POST"])
@login_required
def import_csv():
    """
    Bulk import leads from a CSV file.
    Accepted column names (case-insensitive, flexible):
      business_name / name / business / company
      phone / mobile / contact / phone_number
      email / email_address / mail
      website / url / web / site
      category
      notes / note / remarks
    Skips duplicates silently and reports counts.
    """
    db          = get_db()
    file        = request.files.get("csv_file")
    assigned_to = request.form.get("import_assigned", "user1")
    category    = request.form.get("import_category", "Other")

    if not file or not file.filename.endswith(".csv"):
        flash("Please upload a valid .csv file.", "error")
        return redirect(url_for("dashboard"))

    stream   = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"))
    reader   = csv.DictReader(stream)

    # Normalise header names to lowercase stripped
    raw_headers = reader.fieldnames or []
    headers     = [h.strip().lower() for h in raw_headers]

    # Column name mapping — flexible matching
    def find_col(candidates):
        for c in candidates:
            if c in headers:
                return raw_headers[headers.index(c)]
        return None

    col_name     = find_col(["business_name","name","business","company","business name"])
    col_phone    = find_col(["phone","mobile","contact","phone_number","phone number","mobile number"])
    col_email    = find_col(["email","email_address","mail","email address"])
    col_website  = find_col(["website","url","web","site"])
    col_category = find_col(["category","type","industry"])
    col_notes    = find_col(["notes","note","remarks","description","comment"])

    if not col_name or not col_phone:
        flash("CSV must have at least 'name' and 'phone' columns.", "error")
        return redirect(url_for("dashboard"))

    added    = 0
    skipped  = 0
    errors   = 0
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for row in reader:
        name    = row.get(col_name, "").strip()
        raw_ph  = row.get(col_phone, "").strip()
        email   = row.get(col_email, "").strip() if col_email else None
        website = row.get(col_website, "").strip() if col_website else None
        cat     = row.get(col_category, "").strip() if col_category else None
        notes   = row.get(col_notes, "").strip() if col_notes else None

        if not name or not raw_ph:
            errors += 1
            continue

        # Use CSV category if valid, else use form-selected default
        if cat and cat in CATEGORIES:
            use_cat = cat
        else:
            use_cat = category

        phone  = normalize_phone(raw_ph)
        email  = email or None
        website = website or None
        notes  = notes or None

        # Skip duplicates silently
        if db.execute("SELECT id FROM leads WHERE phone=?", (phone,)).fetchone():
            skipped += 1
            continue
        if email and db.execute("SELECT id FROM leads WHERE email=?", (email,)).fetchone():
            skipped += 1
            continue

        try:
            db.execute(
                "INSERT INTO leads (business_name,phone,email,website,category,notes,status,assigned_to,date_added) VALUES (?,?,?,?,?,?,'New',?,?)",
                (name, phone, email, website, use_cat, notes, assigned_to, date_now)
            )
            db.commit()
            added += 1
        except Exception:
            skipped += 1

    msg = f"Import complete — {added} added, {skipped} skipped (duplicates), {errors} invalid rows."
    flash(msg, "success" if added > 0 else "error")
    return redirect(url_for("dashboard"))


# ── Edit / Delete ──────────────────────────────────────────────────────────────

@app.route("/edit/<int:lead_id>", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id):
    db   = get_db()
    lead = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        db.execute(
            "UPDATE leads SET status=?,notes=?,assigned_to=? WHERE id=?",
            (request.form.get("status", lead["status"]),
             request.form.get("notes","").strip() or None,
             request.form.get("assigned_to", lead["assigned_to"]), lead_id)
        )
        db.commit()
        flash("Lead updated.", "success")
        return redirect(url_for("dashboard"))
    return render_template("edit.html", lead=lead, statuses=STATUSES,
                           users=list(USERS.keys()), current_user=session["user"])

@app.route("/delete/<int:lead_id>", methods=["POST"])
@login_required
def delete_lead(lead_id):
    db = get_db()
    db.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    db.commit()
    flash("Lead deleted.", "success")
    return redirect(url_for("dashboard"))


# ── CSV Exports ────────────────────────────────────────────────────────────────

@app.route("/export/emails")
@login_required
def export_emails():
    rows = get_db().execute(
        "SELECT email FROM leads WHERE email IS NOT NULL AND email!='' ORDER BY id DESC"
    ).fetchall()
    out = io.StringIO()
    csv.writer(out).writerows([["Email"]] + [[r["email"]] for r in rows])
    resp = make_response(out.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=emails.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

@app.route("/export/leads")
@login_required
def export_leads():
    db  = get_db()
    cat = request.args.get("category","")
    if cat:
        rows  = db.execute("SELECT * FROM leads WHERE category=? ORDER BY id DESC",(cat,)).fetchall()
        fname = f"leads_{cat.lower().replace(' ','_')}.csv"
    else:
        rows  = db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        fname = "leads_all.csv"
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["ID","Business Name","Phone","Email","Website","Category","Notes","Status","Assigned To","Date Added"])
    for r in rows:
        w.writerow([r["id"],r["business_name"],r["phone"],r["email"] or "",
                    r["website"] or "",r["category"],r["notes"] or "",
                    r["status"],r["assigned_to"],r["date_added"]])
    resp = make_response(out.getvalue())
    resp.headers["Content-Disposition"] = f"attachment; filename={fname}"
    resp.headers["Content-Type"] = "text/csv"
    return resp


# ── Settings ───────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET","POST"])
@login_required
def settings():
    config = load_config()
    if request.method == "POST":
        config["ai_provider"]   = request.form.get("ai_provider","gemini")
        config["ai_api_key"]    = request.form.get("ai_api_key","").strip()
        config["ai_model"]      = request.form.get("ai_model","").strip()
        config["ai_custom_url"] = request.form.get("ai_custom_url","").strip()
        config["gmail_address"] = request.form.get("gmail_address","").strip()
        config["gmail_password"]= request.form.get("gmail_password","").strip()
        config["sender_name"]   = request.form.get("sender_name","").strip()
        save_config(config)
        flash("Settings saved!", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", config=config,
                           current_user=session["user"],
                           ai_providers=AI_PROVIDERS)


# ── AI Email Generation (multi-provider) ───────────────────────────────────────

def call_ai(config, prompt):
    """
    Universal AI caller. Supports:
    - Gemini (Google's own API format)
    - OpenAI-compatible (OpenAI, Groq, Mistral, Together, custom)
    Returns the generated text string.
    """
    provider   = config.get("ai_provider", "gemini")
    api_key    = config.get("ai_api_key", "").strip()
    model      = config.get("ai_model", "").strip()
    custom_url = config.get("ai_custom_url", "").strip()

    if not api_key:
        raise ValueError("No AI API key set. Go to Settings first.")

    # ── Gemini ──────────────────────────────────────────────────────────────
    if provider == "gemini":
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 500}
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    # ── OpenAI-compatible (OpenAI, Groq, Mistral, custom) ───────────────────
    else:
        if provider == "openai":
            url   = "https://api.openai.com/v1/chat/completions"
            model = model or "gpt-4o-mini"
        elif provider == "groq":
            url   = "https://api.groq.com/openai/v1/chat/completions"
            model = model or "llama-3.3-70b-versatile"
        elif provider == "mistral":
            url   = "https://api.mistral.ai/v1/chat/completions"
            model = model or "mistral-small-latest"
        elif provider == "custom":
            url   = custom_url
            model = model or "gpt-3.5-turbo"
            if not url:
                raise ValueError("Custom URL not set. Go to Settings.")
        else:
            raise ValueError(f"Unknown provider: {provider}")

        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 500,
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        }, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()


def generate_email_with_ai(config, business_name, category, notes, offer, sender_name):
    """Generate a personalised cold email. Returns {subject, body}."""
    prompt = f"""You are an expert cold email copywriter. Write a short personalised cold email.

Business: {business_name}
Category: {category}
Notes: {notes or 'None'}
My offer: {offer}
Sender name: {sender_name}

Rules:
- Under 120 words
- Sound human, not like a template
- Mention the business name naturally
- One clear call to action (reply to this email)
- No emojis

Respond ONLY in this exact JSON format, no markdown, no extra text:
{{"subject": "...", "body": "..."}}"""

    raw = call_ai(config, prompt)

    # Strip markdown fences if model adds them
    if raw.startswith("```"):
        parts = raw.split("```")
        raw   = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ── Campaign ───────────────────────────────────────────────────────────────────

@app.route("/campaign")
@login_required
def campaign():
    db       = get_db()
    config   = load_config()
    category = request.args.get("category","")
    status   = request.args.get("status","New")

    query  = "SELECT * FROM leads WHERE email IS NOT NULL AND email!=''"
    params = []
    if category:
        query += " AND category=?"; params.append(category)
    if status:
        query += " AND status=?";   params.append(status)
    query += " ORDER BY id DESC"
    leads = db.execute(query, params).fetchall()

    logs = db.execute("""
        SELECT cl.*, l.business_name FROM campaign_logs cl
        JOIN leads l ON cl.lead_id=l.id
        ORDER BY cl.id DESC LIMIT 50
    """).fetchall()

    return render_template("campaign.html", leads=leads, logs=logs,
                           categories=CATEGORIES, statuses=STATUSES, config=config,
                           current_user=session["user"], ai_providers=AI_PROVIDERS,
                           active_category=category, active_status=status)


@app.route("/campaign/generate", methods=["POST"])
@login_required
def generate_emails():
    config      = load_config()
    sender_name = config.get("sender_name","").strip() or session["user"]

    if not config.get("ai_api_key","").strip():
        return jsonify({"error": "No AI API key set. Go to Settings first."}), 400

    offer    = request.json.get("offer","").strip()
    lead_ids = request.json.get("lead_ids",[])

    if not offer:    return jsonify({"error": "Please enter your offer."}), 400
    if not lead_ids: return jsonify({"error": "Select at least one lead."}), 400

    db      = get_db()
    results = []

    for lead_id in lead_ids:
        lead = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead or not lead["email"]:
            continue
        try:
            gen = generate_email_with_ai(
                config, lead["business_name"], lead["category"],
                lead["notes"] or "", offer, sender_name
            )
            results.append({"lead_id": lead["id"], "business_name": lead["business_name"],
                            "email": lead["email"], "subject": gen.get("subject",""),
                            "body": gen.get("body","")})
            time.sleep(0.4)
        except Exception as e:
            results.append({"lead_id": lead["id"], "business_name": lead["business_name"],
                            "email": lead["email"], "subject":"","body":"","error": str(e)})

    return jsonify({"emails": results})


@app.route("/campaign/send", methods=["POST"])
@login_required
def send_emails():
    config = load_config()
    gmail_address  = config.get("gmail_address","").strip()
    gmail_password = config.get("gmail_password","").strip()
    sender_name    = config.get("sender_name","").strip() or session["user"]

    if not gmail_address or not gmail_password:
        return jsonify({"error": "Gmail not configured. Go to Settings first."}), 400

    emails_to_send = request.json.get("emails",[])
    if not emails_to_send:
        return jsonify({"error": "No emails to send."}), 400

    db      = get_db()
    sent    = []
    failed  = []
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(gmail_address, gmail_password)
    except Exception as e:
        return jsonify({"error": f"Gmail login failed: {str(e)}"}), 500

    for item in emails_to_send:
        lead_id  = item.get("lead_id")
        to_email = item.get("email")
        subject  = item.get("subject","")
        body     = item.get("body","")
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{sender_name} <{gmail_address}>"
            msg["To"]      = to_email
            msg.attach(MIMEText(body, "plain"))
            server.sendmail(gmail_address, to_email, msg.as_string())
            db.execute("INSERT INTO campaign_logs (lead_id,email,subject,body,status,sent_at) VALUES (?,?,?,?,?,?)",
                       (lead_id, to_email, subject, body, "sent", sent_at))
            db.execute("UPDATE leads SET status='Contacted' WHERE id=?", (lead_id,))
            db.commit()
            sent.append(to_email)
            time.sleep(2)
        except Exception as e:
            db.execute("INSERT INTO campaign_logs (lead_id,email,subject,body,status,sent_at) VALUES (?,?,?,?,?,?)",
                       (lead_id, to_email, subject, body, "failed", sent_at))
            db.commit()
            failed.append({"email": to_email, "error": str(e)})

    server.quit()
    return jsonify({"sent": sent, "failed": failed,
                    "message": f"{len(sent)} sent, {len(failed)} failed."})


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG","false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
else:
    init_db()
