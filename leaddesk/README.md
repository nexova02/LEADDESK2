# LeadDesk — Business Lead Manager

A lightweight, self-hosted lead management system for 2 users.
Built with Flask (Python) + SQLite + vanilla JS. No heavy frameworks.

---

## Project Structure

```
project/
├── app.py               ← Flask backend (all routes + logic)
├── leads.db             ← SQLite database (auto-created on first run)
├── requirements.txt     ← Python dependencies
├── Procfile             ← For Render / Heroku deployment
├── templates/
│   ├── login.html       ← Login page
│   ├── dashboard.html   ← Main lead table + add form
│   └── edit.html        ← Edit lead status/notes
└── static/
    ├── style.css        ← All styles (no Bootstrap)
    └── script.js        ← Minimal JS (delete confirm, phone hint)
```

---

## A. Local Setup

### 1. Install Python 3.10+
Download from https://python.org if you don't have it.

### 2. (Optional) Create a virtual environment
```bash
python -m venv venv
# On Mac/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the app
```bash
python app.py
```

### 5. Open in browser
```
http://127.0.0.1:5000
```

### 6. Login credentials
| Username | Password    |
|----------|-------------|
| user1    | password123 |
| user2    | password123 |

The `leads.db` SQLite file is created automatically on first run.

---

## B. Render Deployment

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 2. Create a Web Service on Render
- Go to https://render.com and sign in
- Click **New → Web Service**
- Connect your GitHub repository

### 3. Configure the service
| Setting         | Value                        |
|-----------------|------------------------------|
| Environment     | Python 3                     |
| Build Command   | `pip install -r requirements.txt` |
| Start Command   | `gunicorn app:app`           |

### 4. Set environment variables (optional but recommended)
In Render's dashboard → Environment tab:
- `SECRET_KEY` → set to a long random string (e.g. output of `python -c "import secrets; print(secrets.token_hex(32))"`)

### 5. Deploy
Click **Create Web Service**. Render will build and deploy automatically.

### ⚠️ Free Tier Limitations
- The app will **spin down** after ~15 minutes of inactivity.
- First request after spin-down takes ~30 seconds to load — this is normal.
- SQLite data persists between deploys **only if** you use a persistent disk.
  - In Render free tier, the filesystem resets on redeploy.
  - For persistent data on Render, either upgrade to a paid plan and add a disk,
    or switch to a free external database like Supabase (PostgreSQL).
  - For local use, SQLite works perfectly.

---

## Features

- ✅ Login / Logout (2 hardcoded users, Flask sessions)
- ✅ Add leads with duplicate phone/email detection
- ✅ Phone normalization (+91 format)
- ✅ Filter by category, status, assigned user
- ✅ Search by name or phone
- ✅ Edit status, notes, assigned user
- ✅ Delete with confirmation
- ✅ Export emails CSV
- ✅ Export leads CSV (all or by category)
- ✅ Clean dark UI, no Bootstrap

---

## Customization Tips

- **Change passwords**: Edit the `USERS` dict in `app.py`
- **Add categories**: Edit the `CATEGORIES` list in `app.py`
- **Change secret key**: Set the `SECRET_KEY` env variable
- **Change port locally**: Set `PORT` env variable or edit `app.py`
