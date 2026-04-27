"""
NEXOVA LeadDesk — Complete Application
Flask + SQLite + Multi-AI + Gmail + CSV Import
"""

import os, csv, io, json, sqlite3, smtplib, time, urllib.request
import imaplib, email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header as dh
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, g, make_response, flash)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nexova-secret-2024")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "leads.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

USERS      = {"user1": "password123", "user2": "password123"}
CATEGORIES = ["Gym", "Salon", "Car Detailing", "Agency", "Other"]
STATUSES   = ["New", "Contacted", "Replied", "Closed"]


# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ═══════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db: db.close()

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
            date_added    TEXT    NOT NULL,
            reply_snippet TEXT
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
            sent_at  TEXT    NOT NULL
        )
    """)
    db.commit()
    db.close()


# ═══════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def normalize_phone(raw):
    """Strip spaces/dashes and ensure +91 prefix."""
    c = raw.strip().replace(" ", "").replace("-", "")
    if not c.startswith("+"):
        c = ("+" + c) if (c.startswith("91") and len(c) == 12) else ("+91" + c)
    return c


# ═══════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════

@app.route("/", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        if USERS.get(u) == p:
            session["user"] = u
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    db       = get_db()
    search   = request.args.get("search", "").strip()
    category = request.args.get("category", "")
    status   = request.args.get("status", "")
    assigned = request.args.get("assigned", "")

    q, p = "SELECT * FROM leads WHERE 1=1", []
    if search:
        q += " AND (business_name LIKE ? OR phone LIKE ? OR email LIKE ?)"
        p += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if category: q += " AND category=?";    p.append(category)
    if status:   q += " AND status=?";      p.append(status)
    if assigned: q += " AND assigned_to=?"; p.append(assigned)
    q += " ORDER BY id DESC"

    leads = db.execute(q, p).fetchall()
    return render_template("dashboard.html",
        leads=leads, categories=CATEGORIES, statuses=STATUSES,
        users=list(USERS.keys()), current_user=session["user"],
        search=search, active_category=category,
        active_status=status, active_assigned=assigned)


# ═══════════════════════════════════════════════════════
# ADD LEAD (manual form)
# ═══════════════════════════════════════════════════════

@app.route("/add", methods=["POST"])
@login_required
def add_lead():
    db   = get_db()
    name = request.form.get("business_name", "").strip()
    raw  = request.form.get("phone", "").strip()
    email   = request.form.get("email", "").strip() or None
    website = request.form.get("website", "").strip() or None
    category= request.form.get("category", "Other")
    notes   = request.form.get("notes", "").strip() or None
    assigned= request.form.get("assigned_to", "user1")

    if not name or not raw:
        flash("Business name and phone are required.", "error")
        return redirect(url_for("dashboard"))

    phone = normalize_phone(raw)

    if db.execute("SELECT id FROM leads WHERE phone=?", (phone,)).fetchone():
        flash(f"Phone {phone} already exists.", "error")
        return redirect(url_for("dashboard"))
    if email and db.execute("SELECT id FROM leads WHERE email=?", (email,)).fetchone():
        flash(f"Email {email} already exists.", "error")
        return redirect(url_for("dashboard"))

    db.execute(
        "INSERT INTO leads (business_name,phone,email,website,category,notes,status,assigned_to,date_added)"
        " VALUES (?,?,?,?,?,?,'New',?,?)",
        (name, phone, email, website, category, notes, assigned,
         datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    db.commit()
    flash("Lead added!", "success")
    return redirect(url_for("dashboard"))


# ═══════════════════════════════════════════════════════
# CSV IMPORT
# ═══════════════════════════════════════════════════════

@app.route("/import", methods=["POST"])
@login_required
def import_csv():
    """
    Upload a CSV file and bulk-add leads.
    Flexible column detection — accepts many naming variations.
    Skips duplicates silently.
    """
    db          = get_db()
    file        = request.files.get("csv_file")
    assigned_to = request.form.get("import_assigned", "user1")
    default_cat = request.form.get("import_category", "Other")

    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please upload a valid .csv file.", "error")
        return redirect(url_for("dashboard"))

    try:
        stream  = io.StringIO(file.stream.read().decode("utf-8-sig", errors="ignore"))
        reader  = csv.DictReader(stream)

        # Normalise headers to lowercase for flexible matching
        raw_headers = reader.fieldnames or []
        norm        = [h.strip().lower().replace(" ", "_") for h in raw_headers]

        def col(candidates):
            """Find the first matching column name."""
            for c in candidates:
                if c in norm:
                    return raw_headers[norm.index(c)]
            return None

        c_name    = col(["business_name","name","business","company","store","brand"])
        c_phone   = col(["phone","mobile","contact","phone_number","mobile_number","tel"])
        c_email   = col(["email","email_address","mail","e-mail","e_mail"])
        c_website = col(["website","url","web","site","link","webpage"])
        c_category= col(["category","type","industry","sector","niche"])
        c_notes   = col(["notes","note","remarks","description","comment","info"])

        if not c_name or not c_phone:
            flash("CSV must have at least a 'name' and 'phone' column.", "error")
            return redirect(url_for("dashboard"))

        added   = 0
        skipped = 0
        bad     = 0
        now     = datetime.now().strftime("%Y-%m-%d %H:%M")

        for row in reader:
            name    = (row.get(c_name) or "").strip()
            raw_ph  = (row.get(c_phone) or "").strip()
            email   = (row.get(c_email) or "").strip() if c_email else ""
            website = (row.get(c_website) or "").strip() if c_website else ""
            cat_raw = (row.get(c_category) or "").strip() if c_category else ""
            notes   = (row.get(c_notes) or "").strip() if c_notes else ""

            if not name or not raw_ph:
                bad += 1
                continue

            phone   = normalize_phone(raw_ph)
            email   = email or None
            website = website or None
            notes   = notes or None
            cat     = cat_raw if cat_raw in CATEGORIES else default_cat

            # Skip duplicates
            if db.execute("SELECT id FROM leads WHERE phone=?", (phone,)).fetchone():
                skipped += 1; continue
            if email and db.execute("SELECT id FROM leads WHERE email=?", (email,)).fetchone():
                skipped += 1; continue

            try:
                db.execute(
                    "INSERT INTO leads (business_name,phone,email,website,category,notes,status,assigned_to,date_added)"
                    " VALUES (?,?,?,?,?,?,'New',?,?)",
                    (name, phone, email, website, cat, notes, assigned_to, now)
                )
                db.commit()
                added += 1
            except Exception:
                skipped += 1

        parts = [f"{added} leads added"]
        if skipped: parts.append(f"{skipped} skipped (duplicates)")
        if bad:     parts.append(f"{bad} rows had missing data")
        flash("Import complete — " + ", ".join(parts) + ".",
              "success" if added > 0 else "error")

    except Exception as e:
        flash(f"Import failed: {str(e)}", "error")

    return redirect(url_for("dashboard"))


# ═══════════════════════════════════════════════════════
# EDIT / DELETE
# ═══════════════════════════════════════════════════════

@app.route("/edit/<int:lead_id>", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id):
    db   = get_db()
    lead = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        flash("Lead not found.", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        db.execute("UPDATE leads SET status=?,notes=?,assigned_to=? WHERE id=?",
                   (request.form.get("status", lead["status"]),
                    request.form.get("notes", "").strip() or None,
                    request.form.get("assigned_to", lead["assigned_to"]),
                    lead_id))
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


# ═══════════════════════════════════════════════════════
# CSV EXPORT
# ═══════════════════════════════════════════════════════

@app.route("/export/emails")
@login_required
def export_emails():
    rows = get_db().execute(
        "SELECT email FROM leads WHERE email IS NOT NULL AND email!='' ORDER BY id DESC"
    ).fetchall()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Email"])
    for r in rows: w.writerow([r["email"]])
    resp = make_response(out.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=emails.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

@app.route("/export/leads")
@login_required
def export_leads():
    db  = get_db()
    cat = request.args.get("category", "")
    if cat:
        rows  = db.execute("SELECT * FROM leads WHERE category=? ORDER BY id DESC", (cat,)).fetchall()
        fname = f"leads_{cat.lower().replace(' ','_')}.csv"
    else:
        rows  = db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        fname = "leads_all.csv"
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["ID","Business Name","Phone","Email","Website","Category","Notes","Status","Assigned To","Date Added"])
    for r in rows:
        w.writerow([r["id"], r["business_name"], r["phone"], r["email"] or "",
                    r["website"] or "", r["category"], r["notes"] or "",
                    r["status"], r["assigned_to"], r["date_added"]])
    resp = make_response(out.getvalue())
    resp.headers["Content-Disposition"] = f"attachment; filename={fname}"
    resp.headers["Content-Type"] = "text/csv"
    return resp


# ═══════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    config = load_config()
    if request.method == "POST":
        config["ai_provider"]   = request.form.get("ai_provider", "groq")
        config["ai_api_key"]    = request.form.get("ai_api_key", "").strip()
        config["ai_model"]      = request.form.get("ai_model", "").strip()
        config["ai_custom_url"] = request.form.get("ai_custom_url", "").strip()
        config["sender_name"]   = request.form.get("sender_name", "").strip()
        config["gmail_address"] = request.form.get("gmail_address", "").strip()
        config["gmail_password"]= request.form.get("gmail_password", "").strip()
        save_config(config)
        flash("Settings saved!", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", config=config, current_user=session["user"])


# ═══════════════════════════════════════════════════════
# AI EMAIL GENERATION — supports any provider
# ═══════════════════════════════════════════════════════

def call_ai(config, prompt):
    """
    Universal AI caller.
    Supports Gemini, OpenAI, Groq, Mistral, or any OpenAI-compatible API.
    """
    provider = config.get("ai_provider", "groq")
    api_key  = config.get("ai_api_key", "").strip()
    model    = config.get("ai_model", "").strip()
    custom_url = config.get("ai_custom_url", "").strip()

    if not api_key:
        raise ValueError("No API key set. Go to Settings and add your key.")

    # ── Gemini uses its own request format ──────────────────────────────
    if provider == "gemini":
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 500}
        }).encode()
        req = urllib.request.Request(url, data=payload,
              headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    # ── All others use OpenAI-compatible format ──────────────────────────
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
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"].strip()


def generate_email_with_ai(config, business_name, category, notes, offer, sender_name):
    """Generate one personalised cold email. Returns {subject, body}."""
    prompt = f"""You are an expert cold email copywriter. Write a short personalised cold email.

Business: {business_name}
Category: {category}
Notes: {notes or 'None'}
My offer: {offer}
Sender: {sender_name}

Rules:
- Under 120 words
- Sound human, conversational
- Mention the business name naturally
- One call to action (reply to this email)
- No emojis, no fluff

Respond ONLY in this exact JSON format with no markdown, no extra text:
{{"subject": "your subject here", "body": "your email body here"}}"""

    raw = call_ai(config, prompt)

    # Strip markdown fences if model wraps in ```json ... ```
    if "```" in raw:
        parts = raw.split("```")
        raw   = parts[1] if len(parts) > 1 else parts[0]
        if raw.lower().startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


# ═══════════════════════════════════════════════════════
# CAMPAIGN
# ═══════════════════════════════════════════════════════

@app.route("/campaign")
@login_required
def campaign():
    db       = get_db()
    config   = load_config()
    category = request.args.get("category", "")
    status   = request.args.get("status", "New")

    q, p = "SELECT * FROM leads WHERE email IS NOT NULL AND email!=''", []
    if category: q += " AND category=?"; p.append(category)
    if status:   q += " AND status=?";   p.append(status)
    q += " ORDER BY id DESC"
    leads = db.execute(q, p).fetchall()

    logs = db.execute("""
        SELECT cl.*, l.business_name FROM campaign_logs cl
        JOIN leads l ON cl.lead_id=l.id
        ORDER BY cl.id DESC LIMIT 50
    """).fetchall()

    return render_template("campaign.html",
        leads=leads, logs=logs, config=config,
        categories=CATEGORIES, statuses=STATUSES,
        current_user=session["user"],
        active_category=category, active_status=status)


@app.route("/campaign/generate", methods=["POST"])
@login_required
def generate_emails():
    config      = load_config()
    sender_name = config.get("sender_name", "").strip() or session["user"]

    if not config.get("ai_api_key", "").strip():
        return jsonify({"error": "No AI key set. Go to Settings first."}), 400

    offer    = (request.json or {}).get("offer", "").strip()
    lead_ids = (request.json or {}).get("lead_ids", [])

    if not offer:    return jsonify({"error": "Enter your offer description."}), 400
    if not lead_ids: return jsonify({"error": "Select at least one lead."}), 400

    db      = get_db()
    results = []

    for lid in lead_ids:
        lead = db.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        if not lead or not lead["email"]:
            continue
        try:
            gen = generate_email_with_ai(
                config, lead["business_name"], lead["category"],
                lead["notes"] or "", offer, sender_name)
            results.append({
                "lead_id": lead["id"], "business_name": lead["business_name"],
                "email": lead["email"], "subject": gen.get("subject", ""),
                "body": gen.get("body", "")
            })
            time.sleep(0.4)
        except Exception as e:
            results.append({
                "lead_id": lead["id"], "business_name": lead["business_name"],
                "email": lead["email"], "subject": "", "body": "", "error": str(e)
            })

    return jsonify({"emails": results})


@app.route("/campaign/send", methods=["POST"])
@login_required
def send_emails():
    config  = load_config()
    gmail   = config.get("gmail_address", "").strip()
    pw      = config.get("gmail_password", "").strip()
    sender  = config.get("sender_name", "").strip() or session["user"]

    if not gmail or not pw:
        return jsonify({"error": "Gmail not configured. Go to Settings."}), 400

    items = (request.json or {}).get("emails", [])
    if not items:
        return jsonify({"error": "No emails to send."}), 400

    # Test login once before starting
    try:
        test = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
        test.login(gmail, pw)
        test.quit()
    except Exception as e:
        return jsonify({"error": f"Gmail login failed: {str(e)}. Check your App Password in Settings."}), 500

    db = get_db()
    sent, failed = [], []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for item in items:
        lid  = item.get("lead_id")
        to   = item.get("email", "")
        subj = item.get("subject", "")
        body = item.get("body", "")

        try:
            # Fresh SMTP connection per email — avoids timeout on multiple sends
            srv = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
            srv.login(gmail, pw)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subj
            msg["From"]    = f"{sender} <{gmail}>"
            msg["To"]      = to
            msg.attach(MIMEText(body, "plain"))
            srv.sendmail(gmail, to, msg.as_string())
            srv.quit()

            db.execute(
                "INSERT INTO campaign_logs (lead_id,email,subject,body,status,sent_at) VALUES (?,?,?,?,?,?)",
                (lid, to, subj, body, "sent", now))
            db.execute("UPDATE leads SET status='Contacted' WHERE id=?", (lid,))
            db.commit()
            sent.append(to)
            time.sleep(1)  # 1s delay — enough to avoid spam, won't timeout

        except Exception as e:
            try:
                db.execute(
                    "INSERT INTO campaign_logs (lead_id,email,subject,body,status,sent_at) VALUES (?,?,?,?,?,?)",
                    (lid, to, subj, body, "failed", now))
                db.commit()
            except Exception:
                pass
            failed.append({"email": to, "error": str(e)})

    return jsonify({
        "sent":    sent,
        "failed":  failed,
        "message": f"{len(sent)} sent, {len(failed)} failed."
    })



# ═══════════════════════════════════════════════════════
# REPLY DETECTION (IMAP)
# ═══════════════════════════════════════════════════════

def decode_str(s):
    """Decode email header string."""
    if s is None:
        return ""
    parts = dh(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            result.append(part)
    return "".join(result)


@app.route("/check-replies", methods=["POST"])
@login_required
def check_replies():
    """
    Connect to Gmail via IMAP, scan inbox for replies from leads,
    update lead status to Replied and store snippet.
    """
    config = load_config()
    gmail  = config.get("gmail_address", "").strip()
    pw     = config.get("gmail_password", "").strip()

    if not gmail or not pw:
        return jsonify({"error": "Gmail not configured. Go to Settings."}), 400

    db = get_db()

    # Get all leads that were contacted — only check those
    leads = db.execute(
        "SELECT id, email, business_name FROM leads WHERE email IS NOT NULL AND status IN ('Contacted','New')"
    ).fetchall()

    if not leads:
        return jsonify({"checked": 0, "replied": 0, "message": "No contacted leads to check."})

    # Build a lookup: email address → lead id
    email_to_lead = {row["email"].lower(): row["id"] for row in leads if row["email"]}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail, pw)
        mail.select("INBOX")
    except Exception as e:
        return jsonify({"error": f"Gmail IMAP login failed: {str(e)}"}), 500

    replied = []

    try:
        # Search all messages in inbox
        _, msg_ids = mail.search(None, "ALL")
        ids = msg_ids[0].split()

        # Only check last 200 emails to keep it fast
        ids = ids[-200:] if len(ids) > 200 else ids

        for mid in ids:
            try:
                _, msg_data = mail.fetch(mid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)

                from_header = decode_str(msg.get("From", ""))
                from_email  = ""

                # Extract email address from From header
                if "<" in from_header and ">" in from_header:
                    from_email = from_header.split("<")[1].split(">")[0].strip().lower()
                else:
                    from_email = from_header.strip().lower()

                # Check if this sender is one of our leads
                if from_email not in email_to_lead:
                    continue

                lead_id = email_to_lead[from_email]

                # Get email body snippet
                snippet = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                snippet = part.get_payload(decode=True).decode("utf-8", errors="ignore")[:300]
                            except Exception:
                                snippet = ""
                            break
                else:
                    try:
                        snippet = msg.get_payload(decode=True).decode("utf-8", errors="ignore")[:300]
                    except Exception:
                        snippet = ""

                snippet = snippet.strip()

                # Update lead status to Replied
                db.execute(
                    "UPDATE leads SET status='Replied', reply_snippet=? WHERE id=? AND status NOT IN ('Closed','Replied')",
                    (snippet, lead_id)
                )
                db.commit()
                replied.append(from_email)

            except Exception:
                continue

        mail.logout()

    except Exception as e:
        return jsonify({"error": f"Error scanning inbox: {str(e)}"}), 500

    return jsonify({
        "checked":  len(ids),
        "replied":  len(set(replied)),
        "emails":   list(set(replied)),
        "message":  f"Scanned {len(ids)} emails. Found {len(set(replied))} replies."
    })

# ═══════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
else:
    init_db()