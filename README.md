# 🌌 Smart Expense Tracker (3D Dark + Neon)

An AI-powered, real-time **Personal Expense Tracker** built with **Django 5**, an interactive **3D WebGL (Three.js)** ambient visual engine, and a bidirectional **Telegram Bot** for seamless on-the-go financial tracking.

---

## ✨ Key Features

- **3D Dark + Neon Cyber UI**: Deep obsidian `#030712` theme with volumetric neon radial glows (cyan, electric purple, hot magenta, mint), 3D perspective tilt cards with specular glares, and luminous neon accents.
- **Three.js 3D WebGL Visual Engines**:
  - **Global Space Canvas**: Floating geometric polyhedrons with emissive neon materials, dual directional light sweeps, and a twinkling field of 300+ neon stardust particles.
  - **3D Financial Core**: Real-time 3D polyhedral nexus reflecting budget health (cyan = optimal, amber = 80% caution, magenta = exceeded), holographic wireframe cage, and dual orbiting energy rings with interactive touch/mouse drag.
  - **Dynamic Currency Coin**: 3D metallic coin with glowing neon rim that accelerates as you enter transaction amounts.
  - **Cyber Vault & Telemetry Beacon**: Interactive 3D objects for authentication and Telegram link verification.
- **Dual Theme Support**: 1-click toggle between **3D Dark + Neon** and clean **Bright Mode**.
- **Telegram Bot Integration**:
  - Auto-starts in a thread when Django server launches (`acquire_bot_lock()` socket protection against conflicts).
  - Quick account linking via deep-link redirect (`/start <link_code>`) or direct 6-digit verification code.
  - Log expenses via natural language or quick commands (`/expense 250 Food`, `/summary`, `/budget 5000`).
- **Interactive Chart.js Analytics**:
  - Spending trends with glowing neon cyan gradients.
  - Dynamic category breakdown doughnut charts.
- **PDF Report Generation**: Download filtered, styled expense reports via ReportLab.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.12+, Django 5.x
- **Database**: SQLite (Development) / PostgreSQL-ready
- **Frontend**: HTML5, Vanilla CSS3 (3D Glassmorphism & Neon Design System), Bootstrap 5.3
- **3D Graphics & Visuals**: Three.js (r128 WebGL Engine)
- **Charts**: Chart.js
- **Telegram Integration**: `python-telegram-bot` (v21+) with async polling & deep linking
- **PDF Export**: ReportLab

---

## 🚀 Quick Start Guide

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/smart-expense-tracker.git
cd smart-expense-tracker
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your settings:
```ini
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

### 5. Apply Migrations & Create Superuser
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Run the Development Server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` in your browser. The Telegram Bot will automatically poll in the background!

### 7. Run Unit Tests
```bash
python manage.py test tracker
```

---

## 📂 Project Structure

```text
Personal Tracker/
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── smart/                  # Django Project Configuration
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
└── tracker/                # Main Application
    ├── models.py           # UserProfile, Expense, Category, MonthlyBudget
    ├── views.py            # Dashboard, Expense CRUD, PDF Export, Telegram Redirect
    ├── urls.py
    ├── bot.py              # Telegram Bot Handlers & Deep-Link Auth
    ├── tests.py            # Automated Unit Tests
    ├── static/
    │   ├── css/styles.css  # 3D Dark + Neon Glassmorphic Styles
    │   └── js/main.js      # Three.js 3D Engines & Theme Switching
    └── templates/tracker/  # HTML Templates
        ├── base.html
        ├── dashboard.html
        ├── expenses.html
        ├── expense_form.html
        ├── login.html
        ├── register.html
        └── profile.html
```

---

## 🔒 Security Note
Never commit your `.env` file or `db.sqlite3` database to a public repository. They are already listed in `.gitignore`.
